"""Builders for small real documents, so format tests need no binary fixtures."""

import zipfile
from pathlib import Path

# A valid 1x1 PNG. Image tests never decode it; the scripted model stands in for vision.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d49444154789c6360000002000001e221bc330000000049454e44ae426082"
)


def make_pdf(path: Path, paragraphs: list[str]) -> Path:
    """A one-page PDF with one text line per paragraph, separated by a wide gap."""
    text = " ".join(f"({paragraph}) Tj 0 -40 Td" for paragraph in paragraphs)
    stream = f"BT /F1 12 Tf 72 720 Td {text} ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    package = "http://schemas.openxmlformats.org/package/2006"
    office = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    main_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            f'<?xml version="1.0"?><Types xmlns="{package}/content-types">'
            '<Default Extension="rels" '
            'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            f'<?xml version="1.0"?><Relationships xmlns="{package}/relationships">'
            f'<Relationship Id="rId1" Type="{office}/officeDocument" '
            'Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document xmlns:w="{namespace}">'
            f"<w:body>{body}</w:body></w:document>",
        )
    return path


def make_pptx(path: Path, slides: list[tuple[str, str]]) -> Path:
    from pptx import Presentation

    deck = Presentation()
    for title, text in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = text
    deck.save(str(path))
    return path
