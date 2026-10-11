from io import BytesIO
from pathlib import PurePosixPath
from pypdf import PdfReader

class InvalidSource(ValueError): pass

def parse(content: bytes, filename: str, max_bytes=10_000_000):
    if not content or len(content)>max_bytes: raise InvalidSource('Source is empty or exceeds upload limit')
    name=PurePosixPath(filename.replace('\\','/')).name
    if not name or len(name)>200: raise InvalidSource('Invalid filename')
    suffix=PurePosixPath(name).suffix.lower()
    if suffix in {'.txt','.md'}:
        try: pages=[content.decode('utf-8-sig')]
        except UnicodeDecodeError: raise InvalidSource('Text must be UTF-8')
        if '\x00' in pages[0]: raise InvalidSource('Binary text is unsupported')
    elif suffix=='.pdf':
        try:
            reader=PdfReader(BytesIO(content),strict=True)
            if reader.is_encrypted or len(reader.pages)>200: raise InvalidSource('Encrypted or oversized PDF is unsupported')
            pages=[p.extract_text() or '' for p in reader.pages]
        except InvalidSource: raise
        except Exception: raise InvalidSource('Invalid PDF')
        if any(not p.strip() for p in pages): raise InvalidSource('Image-only PDF pages require an OCR adapter')
    else: raise InvalidSource('Supported types are TXT, Markdown and text-based PDF')
    if not any(p.strip() for p in pages) or sum(map(len,pages))>200_000: raise InvalidSource('Source text is empty or exceeds extraction limit')
    chunks=[]
    for page,text in enumerate(pages,1):
        for start in range(0,len(text),4000):
            chunks.append({'chunk_id':f'p{page}-{start}','page':page,'page_start':start,'text':text[start:start+4000]})
    return name,chunks
