import os
import json
import csv
import time
import requests
from bs4 import BeautifulSoup
from openai import OpenAI

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

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    r.encoding = r.apparent_encoding
    return r.text

def find_admission_links(school):
    html = fetch(school["url"])
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

def main():
    schools = json.load(open("schools.json", encoding="utf-8"))
    rows = []
    for school in schools:
        try:
            links = find_admission_links(school)
            print(school["name"], "找到", len(links), "个链接")
            for link in links:
                try:
                    detail_html = fetch(link["url"])
                    detail_text = BeautifulSoup(detail_html, "lxml").get_text("\n")
                    data = extract_with_llm(detail_text, link["url"])
                    data["学校"] = school["name"]
                    rows.append(data)
                    time.sleep(3)
                except Exception as e:
                    print("详情失败", link["url"], e)
        except Exception as e:
            print("学校失败", school["name"], e)

    if rows:
        keys = rows[0].keys()
        with open("result.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)

    lines = []
    for r in rows[:20]:
        lines.append(f"{r.get('学校','')} | {r.get('标题','')} | {r.get('报名时间','')} | {r.get('原文链接','')}")
    content = f"共抓到 {len(rows)} 条。<br>前 20 条：<br>" + "<br>".join(lines)
    push_wechat("双一流研招简章更新", content)

if __name__ == "__main__":
    main()
