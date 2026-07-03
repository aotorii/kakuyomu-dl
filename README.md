# kakuyomu-dl

A downloader to fetch novel chapters from web novel sites and write into epub files.

Available sites so far:
 - [kakuyomu](https://kakuyomu.jp)
 - syosetu
    - [naro](https://syosetu.com)
    - [midnight](https://mid.syosetu.com), [nocturne](https://noc.syosetu.com), [moonlight](https://mnlt.syosetu.com)
 - [hameln](https://syosetu.org)

## Environment
```
Python >= 3.11
```

## Usage

```bash
git clone https://github.com/aotorii/kakuyomu-dl.git
```

```bash
cd kakuyomu-dl
```

```bash
pip install -r requirements.txt
```

```bash
python src/main.py -h
```

## Examples
 - Fetch all episodes and build the epub with one line
```bash
python src/main.py fetch [url/series ID] --epub
```

## Configuration
For sites that are protected by cloudflare, you might have to set up the cookies manually for scrapers to bypass cloudflare turnstile challenges. If you don't see any CAPTCHAs popping up when browsing the site, then you are fine to go. Otherwise:
 - Use your browser's developer tools to check the `cf_clearance` cookie value and your `User-Agent` **AFTER** clearing CAPTCHAs on the page. If you don't know how to do it, google it. 
 - Copy paste them to the following `cf_cookies.json` and put it under the repo root after git cloning. You might need to update it if your IP address changes from the one when you solved the challenges or the cookies expire.
```json
{
    "cf_clearance": "paste here (leave the quotation marks as-is)",
    "user_agent": "paste here"
}
```
 - The current CF-infected list:
    - hameln
