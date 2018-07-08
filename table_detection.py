''' Code taken from https://github.com/okfn/pdftables
from pdftables.pdf_document import PDFDocument
from pdftables.pdftables import page_to_tables
from pdftables.display import to_string


filepath = 'example.pdf'
fileobj = open(filepath,'rb')

doc = PDFDocument.from_fileobj(fileobj)

for page_number, page in enumerate(doc.get_pages()):
    tables = page_to_tables(page)

for table in tables:
  print(to_string(table.data))
'''

import PyPDF2
import os

keywords = ('Tabelle', 'tableau') # TODO add more


# counts the number of tables in a given pdf page
def count_tables_page(page):
    page_content = page.extractText()
    i = 0
    for keyword in keywords:
        i += page_content.count(keyword)
    return i

# counts the number of tables in a given pdf document
def count_tables_doc(filename):
    pdf_file = open(filename)
    read_pdf = PyPDF2.PdfFileReader(pdf_file)
    number_of_pages = read_pdf.getNumPages()
    i = 0
    for p in range(0, number_of_pages):
        i += count_tables_page(read_pdf.getPage(p))
    return i


# counts the number of tables in a given directory and its subdirectories
def count_tables_dir(dirname):
    i = 0

    # r=root, d=directories, f = files
    for r, d, f in os.walk(dirname):
        for file in f:
            if ".pdf" in file: # not really required but why not
                i += count_tables_doc(os.path.join(r, file))