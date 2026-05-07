import requests
import re
from urllib.parse import unquote

res = requests.get('https://html.duckduckgo.com/html/?q=site:quora.com+AI+automation+workflow', headers={'User-Agent': 'Mozilla/5.0 (compatible; SignalForge/1.0; +https://signalforge.io)', 'Accept-Language': 'en-US,en;q=0.9'})
print(res.status_code)
# DuckDuckGo uses a redirect URL in the href now, e.g., href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.quora.com..."
urls = re.findall(r'href="(//duckduckgo\.com/l/\?uddg=[^"]+)"', res.text)
for u in urls:
    decoded = unquote(u.split('uddg=')[1].split('&')[0])
    print(decoded)
