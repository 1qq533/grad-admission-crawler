import os
import json
import csv
import time
import urllib3
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

# 忽略 SSL 警告（解决浙江大学证书过期的问题）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN")

client = OpenAI(
    api_key=os.environ["LLM_API_KEY"],
    base_url=os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
)
MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Mobile Safari/537.36"
    )
}

# 固定的字段名，防止大模型乱加字段导致写入崩溃
FIELDNAMES = ["学校", "年份", "标题", "发布时间", "报名时间", "初试时间", "招生专业", "学费", "原文链接"]

def fetch(url):
    # 添加 verify=False 忽略 HTTPS 证书校验
    r = requests.get(url, headers=HEADERS, timeout=25, verify=False)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text

def find_admission_links(school):
    try:
        html = fetch(school["url"])
    except Exception as e:
        print(f"访问学校主页失败 {school['name']}: {e}")
        return []
        
    soup = BeautifulSoup(html, "lxml")
    keywords = ["招生简章", "招生章程", "硕士招生", "博士招生", "招生信息"]
    links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if any(k in text for k in keywords):
            href = requests.compat.urljoin(school["url"], a["href"])
            links.append({"title": text, "url": href})
    seen = set()
    result = []
    for item in links:
        if item["url"] not in seen:
            seen.add(item["url"])
            result.append(item)
    return result[:5]

def extract_with_llm(text, url):
    prompt = f"""
从下面网页文本中提取研究生招生简章信息，只输出 JSON：
{{
  "年份": "",
  "标题": "",
  "发布时间": "",
  "报名时间": "",
  "初试时间": "",
  "招生专业": "",
  "学费": "",
  "原文链接": "{url}"
}}
如果某项没有，填空字符串。

网页文本：
{text[:12000]}
"""
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
    )
    return json.loads(resp.choices[0].message.content)

def push_wechat(title, content):
    if not PUSHPLUS_TOKEN:
        return
    try:
        requests.post(
            "https://www.pushplus.plus/send",
            json={
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content,
                "template": "html",
            },
            timeout=20,
        )
    except Exception as e:
        print("推送失败", e)

def main():
    try:
        schools = json.load(open("schools.json", encoding="utf-8"))
    except Exception as e:
        print("读取 schools.json 失败", e)
        return

    rows = []
    for school in schools:
        print(f"开始处理: {school['name']}")
        links = find_admission_links(school)
        print(f"{school['name']} 找到 {len(links)} 个链接")
        
        for link in links:
            try:
                detail_html = fetch(link["url"])
                detail_text = BeautifulSoup(detail_html, "lxml").get_text("\n")
                data = extract_with_llm(detail_text, link["url"])
                data["学校"] = school["name"]
                rows.append(data)
                time.sleep(3)
            except Exception as e:
                print(f"详情解析失败 {link['url']}: {e}")
                continue

    # 清洗数据，强制对齐字段
    cleaned_rows = []
    for row in rows:
        cleaned = {k: row.get(k, "") for k in FIELDNAMES}
        cleaned_rows.append(cleaned)

    if cleaned_rows:
        with open("result.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(cleaned_rows)
        print("CSV 写入完成")

    lines = []
    for r in cleaned_rows[:20]:
        lines.append(f"{r.get('学校','')} | {r.get('标题','')} | {r.get('报名时间','')} | {r.get('原文链接','')}")
    
    if lines:
        content = f"共抓到 {len(cleaned_rows)} 条。<br>前 20 条：<br>" + "<br>".join(lines)
        push_wechat("双一流研招简章更新", content)
        print("推送完成")
    else:
        print("没有抓到任何数据，跳过推送")

if __name__ == "__main__":
    main()
