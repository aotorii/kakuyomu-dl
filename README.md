# kakuyomu-dl

A downloader to fetch novel chapters from web novel sites and write into epub files.

Available sites so far:
 - [kakuyomu](https://kakuyomu.jp)
 - syosetu
    - [naro](https://syosetu.com)
    - [midnight](https://mid.syosetu.com), [nocturne](https://noc.syosetu.com), [moonlight](https://mnlt.syosetu.com)
 - [hameln](https://syosetu.org)
 - [akatsuki](https://www.akatsuki-novels.com)
 - [novelup+](https://novelup.plus)

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

```
usage: kakuyomu-dl [-h] [--delay SECONDS] {toc,fetch,epub,check,bookmark} ...

A downloader to download chapters from web novels and write into epub files.

positional arguments:
  {toc,fetch,epub,check,bookmark}
    toc                 list all episodes for a novel
    fetch               fetch episode content
    epub                build an epub from already fetched episodes
    check               check for new episodes
    bookmark            list your bookmarks

options:
  -h, --help            show this help message and exit
  --delay SECONDS       delay between http requests
```

```
usage: kakuyomu-dl fetch [-h] [--episodes SPEC] [--out-dir DIR] [--no-overwrite] [--epub] [--epub-out-dir DIR]
                         [--epub-clean] [--no-illus] [--batch-size N]
                         series

positional arguments:
  series              series ID or full web url

options:
  -h, --help          show this help message and exit
  --episodes SPEC     select the episodes you want to fetch, examples: '1-7' or '1,3-5,7'
  --out-dir DIR       directory to write files into
  --no-overwrite      skip episodes whose xhtml file already exists
  --epub              build an epub immediately after fetching episodes
  --epub-out-dir DIR  where to write the epub file when using --epub
  --epub-clean        remove possible sale promotion in the novel title when using --epub
  --no-illus          skip fetching illustrations from episode pages
  --batch-size N      number of files processed per batch
```

```
usage: kakuyomu-dl epub [-h] [--xhtml-dir DIR] [--out-dir DIR] [--filename NAME] [--cover PATH] [--clean] series

positional arguments:
  series           series ID or full web url

options:
  -h, --help       show this help message and exit
  --xhtml-dir DIR  directory containing the episode files
  --out-dir DIR    where to write the epub file
  --filename NAME  override the output filename
  --cover PATH     set a cover for the epub (1400x2000px for the best)
  --clean          remove possible sale promotion in the novel title
```

```
usage: kakuyomu-dl bookmark [-h] [--check | --update | --delete INDEX [INDEX ...] | --add SERIES [SERIES ...]]

options:
  -h, --help            show this help message and exit
  --check               check update for all the series on the bookmark list
  --update              update all the series on the bookmark list
  --delete INDEX [INDEX ...]
                        delete series from your bookmark list
  --add SERIES [SERIES ...]
                        add series to your bookmark list
```

## Examples
 - Fetch all episodes and build the epub with one line
```bash
python src/main.py fetch [url/series ID] --epub
```

## Configuration
For sites that are protected by cloudflare, you might have to set up the cookies manually for scrapers to bypass cloudflare turnstile challenges. If you don't see any CAPTCHAs popping up when browsing the site, then you are fine to go. Otherwise:
 - Use your browser's developer tools to check the `cf_clearance` cookie value and your `User-Agent` **AFTER** clearing CAPTCHAs on the page. If you don't know how to do it, google it. 
 - Copy paste them to the following `cf_cookies.json` and put it under the config directory after git cloning. You might need to update it if your IP address changes from the one when you solved the challenges or the cookies expire.
```json
{
    "cf_clearance": "paste here (leave the quotation marks as-is)",
    "user_agent": "paste here"
}
```
 - The current CF-infected list:
    - hameln

## Issues
 1. About akatsuki, it is normal that it takes much more time to fetch/check an akatsuki series that is longer than **300** episodes, in which case the site will chop the whole eplist into small chunks (20 episodes per page) automatically, which is extremely concerning. In order to scrape the complete toc, the downloader needs to request at least once for each page. As a result, it takes about 1 minute to finish the toc for, for example, an 1000-episode-series with the default request delay (1s) and even longer based on your network status. As far as I know, there is no other alternative methods to obtain full eplists at the moment.
 2. Be polite. Use `--delay` to adjust the request delay if the server refuses your frequent requests.