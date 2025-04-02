import os
import sys
import re
import fitz  # PyMuPDF
from ebooklib import epub

def load_css(css_path):
    """Loads CSS from an external file."""
    with open(css_path, 'r', encoding='utf-8') as f:
        return f.read()

def create_chapter(title, content, filename):
    """
    Creates an XHTML chapter using semantic HTML.
    If a title is provided, it's added as an <h1>; content is wrapped in an <article>.
    """
    header_html = f'<h1>{title}</h1>' if title.strip() else ''
    chapter = epub.EpubHtml(title=title, file_name=filename, lang='es')
    chapter.content = f'''<html xmlns="http://www.w3.org/1999/xhtml">
  <head>
    <title>{title}</title>
    <link href="styles/custom.css" rel="stylesheet" type="text/css" />
  </head>
  <body>
    {header_html}
    <article epub:type="chapter" class="article-chapter">
      {content}
    </article>
  </body>
</html>'''
    return chapter

def parse_toc_text(text):
    """
    Parses a Spanish TOC page for lines like:
         Parte 1 ........ 7
    Ignores lines that contain "Contenido".
    Returns a list of tuples: (chapter_title, starting_page).
    """
    toc_entries = []
    lines = text.splitlines()
    pattern = re.compile(r'^(?!.*Contenido)(.*?)(?:\s*\.+\s*|\s+-\s+)(\d+)$', re.IGNORECASE)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        match = pattern.match(line)
        if match:
            title = match.group(1).strip()
            try:
                page_num = int(match.group(2).strip())
                toc_entries.append((title, page_num))
            except ValueError:
                continue
    return toc_entries

def combine_pages(page_contents, start, end):
    """Combines the content of pages from start to end (inclusive)."""
    combined = ""
    for p in range(start, end + 1):
        if p in page_contents:
            combined += page_contents[p]
    return combined

def pdf_to_epub(pdf_path, epub_path, toc_page=None):
    """
    Converts a PDF into a reflowable EPUB using logical structure.
    
    Parameters:
      pdf_path:  path to the input PDF.
      epub_path: path to the output EPUB.
      toc_page:  (optional) 1-based page number of the TOC ("Contenido") page.
                That page is used to parse chapter boundaries and is skipped from content.
                
    Note: The first page of the PDF is used as the cover image and is not included
          in the main content.
    """
    doc = fitz.open(pdf_path)
    total_pages = doc.page_count

    # Create the EPUB book.
    book = epub.EpubBook()
    book.set_identifier("id123456")
    book.set_title(os.path.basename(pdf_path))
    book.set_language("es")
    book.add_author("Desconocido")
    
    # === Extract the Cover from the First Page ===
    cover_page = doc[0]
    cover_pix = cover_page.get_pixmap()
    cover_data = cover_pix.tobytes("png")
    book.set_cover("cover.png", cover_data)
    
    # === Process Content Pages (skip the first page, used as cover) ===
    # Content pages: from page 2 to total_pages.
    content_page_numbers = list(range(2, total_pages + 1))
    
    # Dictionary to hold content for each page.
    page_contents = {}
    # List to store image details as tuples: (filename, image bytes).
    images_list = []
    image_counter = 1

    for i in range(1, total_pages):  # start at 1 (i.e. page 2 in 0-indexed list)
        page = doc[i]
        text = page.get_text("text")
        formatted_text = text.replace("\n", "<br/>")
        image_html = ""
        # Extract images from the page.
        for img in page.get_images(full=True):
            xref = img[0]
            pix = fitz.Pixmap(doc, xref)
            if pix.n >= 5:  # Convert CMYK to RGB.
                pix = fitz.Pixmap(fitz.csRGB, pix)
            img_bytes = pix.tobytes("png")
            img_filename = f"images/img_{image_counter}.png"
            image_html += f"<div><img src='{img_filename}' alt='Image {image_counter}' /></div>"
            images_list.append((img_filename, img_bytes))
            image_counter += 1
            pix = None
        # Append a marker with the original PDF page number.
        formatted_text += f"<br/><span class='page-ref'>[Página {i+1}]</span>"
        # Save the combined content (text and images).
        # Note: In the EPUB, this page corresponds to the original PDF page i+1.
        page_contents[i+1] = formatted_text + image_html

    # Add all extracted images to the EPUB.
    for (img_filename, img_bytes) in images_list:
        uid = os.path.splitext(os.path.basename(img_filename))[0]
        img_item = epub.EpubItem(uid=uid,
                                 file_name=img_filename,
                                 media_type="image/png",
                                 content=img_bytes)
        book.add_item(img_item)

    # Determine which pages to include as content.
    if toc_page is not None:
        # Exclude both cover (page 1) and the TOC page.
        content_pages = [p for p in content_page_numbers if p != toc_page]
    else:
        content_pages = content_page_numbers

    # Parse TOC entries from the specified TOC page (if provided).
    toc_entries = []
    if toc_page is not None and toc_page in content_page_numbers:
        toc_text = doc[toc_page - 1].get_text("text")
        toc_entries = parse_toc_text(toc_text)
    
    chapters = []
    if toc_entries:
        toc_entries = sorted(toc_entries, key=lambda x: x[1])
        # If there are pages before the first TOC entry, create a "Prefacio" chapter.
        first_entry_page = toc_entries[0][1]
        if first_entry_page > min(content_pages):
            preface_text = combine_pages(page_contents, min(content_pages), first_entry_page - 1)
            chap = create_chapter("Prefacio", preface_text, "chapter_prefacio.xhtml")
            chapters.append(chap)
        # Create one chapter per TOC entry.
        for idx, entry in enumerate(toc_entries):
            title, start_page = entry
            # Skip the TOC page if it falls in the range.
            if start_page == toc_page:
                continue
            if idx < len(toc_entries) - 1:
                next_entry_page = toc_entries[idx + 1][1]
                end_page = next_entry_page - 1
            else:
                end_page = max(content_pages)
            chapter_text = combine_pages(page_contents, start_page, end_page)
            chap = create_chapter(title, chapter_text, f"chapter_{idx+1}.xhtml")
            chapters.append(chap)
    else:
        # Fallback: combine all content pages into one chapter.
        all_text = combine_pages(page_contents, min(content_pages), max(content_pages))
        chap = create_chapter("Contenido", all_text, "chapter_1.xhtml")
        chapters.append(chap)

    # Load external CSS.
    css_path = os.path.join(os.path.dirname(__file__), "styles", "custom.css")
    custom_css = load_css(css_path)
    css_item = epub.EpubItem(uid="style_nav",
                             file_name="styles/custom.css",
                             media_type="text/css",
                             content=custom_css)
    book.add_item(css_item)

    # Add chapters to the book.
    for chap in chapters:
        book.add_item(chap)

    # Build the EPUB navigation.
    toc_nav = []
    for chap in chapters:
        toc_nav.append(epub.Link(chap.file_name, chap.title, chap.file_name))
    book.toc = tuple(toc_nav)
    
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    
    book.spine = ['nav'] + chapters

    epub.write_epub(epub_path, book, {})

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python pdf_to_epub.py input.pdf output.epub [toc_page]")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    epub_file = sys.argv[1].replace(".pdf", ".epub")
    toc_page_arg = int(sys.argv[2]) if len(sys.argv) == 3 else None
    
    pdf_to_epub(pdf_file, epub_file, toc_page_arg)


    print("EPUB file created successfully.")