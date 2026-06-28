# kakuyomu-dl

A downloader to fetch novel chapters from web novel sites and write into epub files.

Available sites so far:
 - [kakuyomu](https://kakuyomu.jp)
 - syosetu
    - [naro](https://syosetu.com)
    - [midnight](https://mid.syosetu.com), [nocturne](https://noc.syosetu.com), [moonlight](https://mnlt.syosetu.com)

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