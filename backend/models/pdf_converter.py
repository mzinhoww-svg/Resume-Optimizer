import os
import re
import pymupdf as fitz
import markdown
from llm import generate_optimized_resume
from weasyprint import HTML 

# Define base directories (relative to this file, so it works on any OS)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

# Ensure output directory exists
os.makedirs(OUTPUT_DIR, exist_ok=True)

def pdf_to_markdown(pdf_path):
    """Extract text from a PDF and convert it into Markdown format."""
    md_content = []
    doc = fitz.open(pdf_path)

    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text").strip()
        if text:
            md_content.append(f"# Page {page_num}\n")
            md_content.append("```")
            md_content.append(text)
            md_content.append("```\n")

    return "\n".join(md_content)

def save_markdown_to_file(markdown_content, filename):
    """Save Markdown content to a file."""
    file_path = os.path.join(OUTPUT_DIR, filename)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(markdown_content)
    return file_path

def markdown_to_pdf(input_md, output_pdf, css_path=None):
    """
    Convert a Markdown file or string to a well-formatted PDF.
    
    Args:
        input_md (str): Path to the Markdown file or Markdown string.
        output_pdf (str): Path where the output PDF will be saved.
        css_path (str, optional): Path to a custom CSS file for styling.
    """

    if os.path.isfile(input_md):
        with open(input_md, 'r', encoding='utf-8') as f:
            md_content = f.read()
    else:
        md_content = input_md

    # Python-Markdown only starts a list after a blank line; LLMs often omit it
    md_content = re.sub(r'(?m)^([^\s\-*+\d][^\n]*)\n(?=[-*+] )', r'\1\n\n', md_content)

    md = markdown.Markdown(extensions=['extra', 'codehilite', 'toc'])
    html_content = md.convert(md_content)
    # Markdown links left inside raw HTML blocks (e.g. a centered contact <p>) are not converted
    html_content = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+|mailto:[^)\s]+)\)',
                          r'<a href="\2">\1</a>', html_content)

    default_css = """
    @page {
        size: A4;
        margin: 1.2cm 1.4cm;
        @bottom-right {
            content: "Page " counter(page) " of " counter(pages);
            font-size: 8pt;
            color: #666;
        }
    }
    body {
        font-family: "Helvetica", "Arial", sans-serif;
        font-size: 9.5pt;
        line-height: 1.35;
        color: #333;
    }
    h1 {
        font-size: 20pt;
        font-weight: bold;
        color: #1a2a44;
        border-bottom: 2px solid #1a2a44;
        margin: 0 0 4pt;
    }
    h2 {
        font-size: 12pt;
        color: #1a2a44;
        border-bottom: 1px solid #1a2a44;
        margin: 9pt 0 3pt;
    }
    h3 {
        font-size: 10pt;
        margin: 6pt 0 0;
    }
    p { margin: 2pt 0; }
    ul { margin: 2pt 0 2pt; padding-left: 16pt; }
    li { margin: 0; }
    """

    if css_path and os.path.isfile(css_path):
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()
    else:
        css = default_css

    html_with_style = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>{css}</style>
    </head>
    <body>
        {html_content}
    </body>
    </html>
    """

    try:
        HTML(string=html_with_style).write_pdf(output_pdf)
        print(f"Converted Markdown to PDF: {output_pdf}")
    except Exception as e:
        print(f"Error converting Markdown to PDF: {e}")
        raise


if __name__ == "__main__":
    input_pdf_path = os.path.join(UPLOADS_DIR, "resume.pdf")
    md_file_path = os.path.join(OUTPUT_DIR, "Optimized_Resume.md")
    pdf_file_path = os.path.join(OUTPUT_DIR, "Formatted_Resume.pdf")
    
    md_content = pdf_to_markdown(input_pdf_path)
    
    job_description = (
        "We are looking for a software engineer with experience in Python, Java, and SQL. "
        "The ideal candidate should have experience with web development and cloud technologies like AWS and Azure. "
        "Strong problem-solving skills and the ability to work in a team are essential."
    )
    
    optimized_markdown = generate_optimized_resume(md_content, job_description)
    print(optimized_markdown)
    
    save_markdown_to_file(optimized_markdown, "Optimized_Resume.md")
    
    markdown_to_pdf(md_file_path, pdf_file_path)
    
    print("✅ Process completed successfully!")
