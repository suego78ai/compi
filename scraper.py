import sys
import traceback
import pandas as pd
import requests
from bs4 import BeautifulSoup
import re
import io

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

try:
    def sanitize_sheet_name(name):
        name = re.sub(r'[\\\\/\?\*\[\]\:]', '', name)
        return name[:31]

    url = 'https://addon.jinhakapply.com/RatioV1/RatioH/Ratio41260471.html'
    response = requests.get(url)
    response.encoding = 'utf-8'
    soup = BeautifulSoup(response.text, 'html.parser')

    titles = []
    tables = []

    for table_tag in soup.find_all('table'):
        classes = table_tag.get('class', [])
        if 'tableRatio2' in classes or 'tableRatio3' in classes:
            h2 = table_tag.find_previous('h2')
            title = h2.text.strip() if h2 else f"Sheet{len(tables)+1}"
            title = ' '.join(title.split())
            titles.append(title)
            
            df_list = pd.read_html(io.StringIO(str(table_tag)))
            if df_list:
                tables.append(df_list[0])

    # 1. Create Excel File
    with pd.ExcelWriter('경쟁률_현황.xlsx', engine='openpyxl') as writer:
        for i, (table, title) in enumerate(zip(tables, titles)):
            sheet_name = sanitize_sheet_name(title)
            if not sheet_name:
                sheet_name = f'Sheet{i+1}'
            
            table.to_excel(writer, sheet_name=sheet_name, index=False)

    # 2. Create HTML Web App
    html_template = """
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>인하공업전문대학 경쟁률 현황</title>
        <link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css" rel="stylesheet">
        <style>
            :root {{
                --bg-color: #0f172a;
                --glass-bg: rgba(30, 41, 59, 0.7);
                --glass-border: rgba(255, 255, 255, 0.1);
                --text-main: #f8fafc;
                --text-muted: #94a3b8;
                --accent: #3b82f6;
                --accent-hover: #60a5fa;
                --table-header: rgba(15, 23, 42, 0.8);
                --row-hover: rgba(59, 130, 246, 0.15);
            }}
            
            * {{
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }}
            
            body {{
                font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, 'Helvetica Neue', 'Segoe UI', 'Apple SD Gothic Neo', 'Noto Sans KR', 'Malgun Gothic', sans-serif;
                background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
                background-attachment: fixed;
                color: var(--text-main);
                min-height: 100vh;
                padding: 2rem;
                display: flex;
                flex-direction: column;
                align-items: center;
            }}
            
            .container {{
                width: 100%;
                max-width: 1200px;
                background: var(--glass-bg);
                backdrop-filter: blur(20px);
                -webkit-backdrop-filter: blur(20px);
                border: 1px solid var(--glass-border);
                border-radius: 24px;
                padding: 2.5rem;
                box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.6);
                animation: fadeIn 0.8s ease-out;
            }}
            
            h1 {{
                text-align: center;
                font-size: 2.5rem;
                font-weight: 800;
                margin-bottom: 2.5rem;
                background: linear-gradient(to right, #60a5fa, #a78bfa, #f472b6);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                letter-spacing: -0.025em;
                text-shadow: 0 4px 12px rgba(0,0,0,0.1);
            }}
            
            .tabs {{
                display: flex;
                flex-wrap: wrap;
                gap: 0.75rem;
                margin-bottom: 2rem;
                justify-content: center;
            }}
            
            .tab-btn {{
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid var(--glass-border);
                color: var(--text-muted);
                padding: 0.75rem 1.5rem;
                border-radius: 12px;
                cursor: pointer;
                font-weight: 600;
                font-size: 1rem;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }}
            
            .tab-btn:hover {{
                background: rgba(255, 255, 255, 0.1);
                color: var(--text-main);
                transform: translateY(-2px);
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
            }}
            
            .tab-btn.active {{
                background: var(--accent);
                color: white;
                border-color: var(--accent-hover);
                box-shadow: 0 4px 15px rgba(59, 130, 246, 0.5);
            }}
            
            .tab-content {{
                display: none;
                animation: slideUp 0.5s cubic-bezier(0.16, 1, 0.3, 1);
            }}
            
            .tab-content.active {{
                display: block;
            }}
            
            .table-responsive {{
                overflow-x: auto;
                border-radius: 16px;
                border: 1px solid var(--glass-border);
                background: rgba(0, 0, 0, 0.25);
            }}
            
            table {{
                width: 100%;
                border-collapse: collapse;
                text-align: left;
            }}
            
            th, td {{
                padding: 1.25rem 1rem;
                border-bottom: 1px solid var(--glass-border);
            }}
            
            th {{
                background: var(--table-header);
                font-weight: 700;
                color: var(--accent-hover);
                white-space: nowrap;
                position: sticky;
                top: 0;
                z-index: 10;
                letter-spacing: -0.025em;
            }}
            
            tr {{
                transition: all 0.2s ease;
            }}
            
            tbody tr:hover {{
                background: var(--row-hover);
                transform: scale(1.002);
            }}
            
            tbody tr:last-child td {{
                border-bottom: none;
            }}
            
            /* Hide the original index column if it's there */
            table.dataframe {{
                border: none;
            }}
            
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: scale(0.98); }}
                to {{ opacity: 1; transform: scale(1); }}
            }}
            
            @keyframes slideUp {{
                from {{ opacity: 0; transform: translateY(20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            
            @media (max-width: 768px) {{
                .container {{ padding: 1.5rem; }}
                h1 {{ font-size: 1.75rem; margin-bottom: 1.5rem; }}
                .tab-btn {{ padding: 0.6rem 1.2rem; font-size: 0.875rem; }}
            }}
        </style>
    </head>
    <body>

    <div class="container">
        <h1>인하공업전문대학 경쟁률 대시보드</h1>
        <div class="tabs">
            {tabs_html}
        </div>
        <div class="tab-contents">
            {tables_html}
        </div>
    </div>

    <script>
        function openTab(tabId) {{
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            
            document.getElementById(tabId).classList.add('active');
            document.querySelector(`button[onclick="openTab('${{tabId}}')"]`).classList.add('active');
        }}
    </script>
    </body>
    </html>
    """

    tabs_html = ""
    tables_html = ""
    for i, (table, title) in enumerate(zip(tables, titles)):
        tab_id = f"tab_{i}"
        active_class = "active" if i == 0 else ""
        tabs_html += f"""<button class="tab-btn {active_class}" onclick="openTab('{tab_id}')">{title}</button>\n"""
        
        # Render table as HTML
        # Remove pandas specific classes and add our own
        table_html = table.to_html(index=False, classes=[], border=0)
        table_html = table_html.replace('class="dataframe"', '')
        table_html = table_html.replace('border="0"', '')
        table_html = table_html.replace('style="text-align: right;"', '')
        
        tables_html += f"""
        <div id="{tab_id}" class="tab-content {active_class}">
            <div class="table-responsive">
                {table_html}
            </div>
        </div>
        """

    final_html = html_template.format(tabs_html=tabs_html, tables_html=tables_html)

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(final_html)

    print("HTML Web App successfully created.")
except Exception as e:
    with open('error_log.txt', 'w', encoding='utf-8') as f:
        f.write(f"Error: {e}\n")
        traceback.print_exc(file=f)
    print("An error occurred. Check error_log.txt")
