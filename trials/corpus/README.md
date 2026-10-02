# Real-book corpus / 真实书籍语料

**English** — The books used by `trials/realbook_eval.py` (results in `docs/EVALUATION.md`). The PDFs are not stored in the repository (the Spanish book alone is 186 MB). Download them into this folder with:

**中文** — 供 `trials/realbook_eval.py` 使用的书籍（结果见 `docs/EVALUATION.zh-CN.md`）。PDF 文件不存放在仓库中（仅西班牙文那本就有 186 MB）。用下面的命令把它们下载到本文件夹：

```
python trials/get_corpus.py
```

| File / 文件 | Book / 书籍 | Source / 来源 |
|---|---|---|
| `es-openstax-quimica-2ed.pdf` | OpenStax, *Química 2e* (Spanish / 西班牙文; CC BY 4.0) | https://assets.openstax.org/oscms-prodcms/media/documents/Quimica-2ed-WEB.pdf |
| `zh-d2l-pytorch.pdf` | 《动手学深度学习》PyTorch 版 / *Dive into Deep Learning* (Chinese / 中文) | https://zh-v2.d2l.ai/d2l-zh-pytorch.pdf |
| `ja-mext-joho1-ch1.pdf` | 文部科学省「情報I」教員研修用教材 第1章 / MEXT *Information I* teacher materials, ch. 1 (Japanese / 日文) | https://www.mext.go.jp/content/20200722-mxt_jogai02-100013300_003.pdf |
| `de-bpb-izpb332-demokratie.pdf` | bpb, *Informationen zur politischen Bildung* 332: *Demokratie* (German / 德文) | https://www.bpb.de/system/files/dokument_pdf/170510_BPB_667-17_IzpB%20332%20Demokratie_10_barrierefrei.pdf |
| `en-scan-household-chemistry-1914.pdf` | J. F. Snell, *Elementary Household Chemistry* (1914, scan / 扫描件; public domain / 公有领域) | https://archive.org/download/elementaryhouse00snelgoog/elementaryhouse00snelgoog.pdf |

Check each publisher's terms before reusing a book. The sixth book in the evaluation (a scanned Chinese textbook supplied by a user) is copyrighted and is not part of the corpus.

再利用任何一本书之前，请先查看出版方的使用条款。评估中的第六本书（一位用户提供的扫描版中文教科书）受版权保护，不在本语料中。
