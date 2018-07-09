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
# Possible bugfix
from PyPDF2 import PdfFileReader, utils
from io import StringIO
import subprocess

keywords = ('\nTableau', '\nTabelle', '\nTabella', '\nTable') # TODO add more


# counts the number of tables in a given pdf page
def count_tables_page(page):
    page_content = page.extractText()
    print(page_content)
    i = 0
    for keyword in keywords:
        i += page_content.count(keyword)
    return i


# counts the number of tables in a given pdf document
def count_tables_doc(pdf_file):
    try:
        read_pdf = PyPDF2.PdfFileReader(pdf_file)
    except PyPDF2.utils.PdfReadError:
        return -1

    number_of_pages = read_pdf.getNumPages()
    i = 0
    for p in range(0, number_of_pages):
        i += count_tables_page(read_pdf.getPage(p))
    return i


# counts the number of tables in a given directory and its subdirectories
def count_tables_dir(dirname):
    n_tables = 0
    n_errors = 0
    print('dirname: ' + dirname)

    # r=root, d=directories, f = files
    for r, d, f in os.walk(dirname):
        for file in f:
            if ".pdf" in file: # not really required but why not
                pdf_file = open(os.path.join(r, file), mode='rb')

                # Need to catch tables that haven't been fully downloaded and don't have EOFMarker
                i = count_tables_doc(pdf_file)
                if i < 0:
                    n_errors += 1
                else:
                    n_tables += i
    return n_tables, n_errors


'''
# Getting weird EOF marker not found errors
# try solution from https://codedprojects.wordpress.com/2017/06/09/how-to-fix-pypdf-error-eof-marker-not-found/
def decompress_pdf(temp_buffer):
    temp_buffer.seek(0)  # Make sure we're at the start of the file.

    process = subprocess.Popen(['pdftk.exe',
                                '-',  # Read from stdin.
                                'output',
                                '-',  # Write to stdout.
                                'uncompress'],
                               stdin=temp_buffer,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    return StringIO(stdout)


                with open(os.path.join(r, file), encoding='latin1') as input_file:
                    input_buffer = StringIO(input_file.read())
                try:
                    input_pdf = PdfFileReader(input_buffer)
                except utils.PdfReadError:
                    input_pdf = PdfFileReader(decompress_pdf(input_file))
                i += count_tables_doc(input_pdf)
'''


