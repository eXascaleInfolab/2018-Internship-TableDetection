import os
import csv
import tabula
import PyPDF2

# CONSTANTS
SMALL_TABLE_LIMIT = 10
MEDIUM_TABLE_LIMIT = 20

# Create a json string for given path
# source: https://stackoverflow.com/questions/25226208/represent-directory-tree-as-json
def path_dict(path):
    #p = path.encode('cp1252')
    p = path
    i = path

    # while (len(os.listdir(i)) == 1):

    d = {'name': os.path.basename(p)}
    if os.path.isdir(p):
        d['type'] = "directory"
        d['children'] = [path_dict(os.path.join(p, x)) for x in os.listdir(p)]
        d['npdf'] = path_number_of_files(p) # Really bad, but quick way out
    else:
        d['type'] = "file"
        if ".pdf" in p:
            d['npdf'] = 1
        else:
            d['npdf'] = 0
    return d


# TODO write a Bottom up or DP method to make it faster ! (ask Akansha)
# finds the number of files in given path
def path_number_of_files(path):
    n_files = sum([len(list(filter(lambda f: ".pdf" in f, files))) for r, d, files in os.walk(path)])
    return n_files


# Uses Tabula to detect and extract tables from the pdf's
def pdf_stats(path, n_pdf):
    stats = {}
    n_success = 0
    n_error = 0

    for dir_, _, files in os.walk(path):

        # Keep track of successful and unsuccessful files

        for fileName in files:
            if ".pdf" in fileName:
                rel_file = os.path.join(dir_, fileName)
                print("Number errors: %d" % (n_error,))
                print("Number successes: %d" % (n_success,))
                print(stats)

                try:
                    # STEP 0: set all counter to 0
                    n_pages = 0
                    n_table_pages = 0
                    n_table_rows = 0
                    table_sizes = {'small': 0, 'medium': 0, 'large': 0}

                    # STEP 1: count total number of pages
                    pdf_file = PyPDF2.PdfFileReader(open(rel_file, mode='rb'))
                    n_pages = pdf_file.getNumPages()

                    # STEP 2: run TABULA to extract table from every page
                    for i in range(1, n_pages+1):
                        tabula.convert_into(rel_file, "output.csv", output_format='csv', pages="%d" % (i,))

                        # STEP 3: count number of lines of csv
                        fileObject = csv.reader(open("output.csv"))
                        rows = sum(1 for _ in fileObject)
                        n_table_rows += rows
                        if rows > 0:
                            n_table_pages += 1

                            # Add table stats
                            if rows <= SMALL_TABLE_LIMIT:
                                table_sizes['small'] += 1
                            elif rows <= MEDIUM_TABLE_LIMIT:
                                table_sizes['medium'] += 1
                            else:
                                table_sizes['large'] += 1

                    # STEP 4: save stats
                    creation_date = pdf_file.getDocumentInfo()['/CreationDate']
                    stats[fileName] = {'n_pages': n_pages, 'n_tables_pages': n_table_pages,
                                       'n_table_rows': n_table_rows, 'creation_date': creation_date,
                                       'table_sizes': table_sizes, 'url': rel_file}

                    print("Tabula Conversion done for %s" % (fileName,))
                    n_success = n_success + 1

                    if n_success >= n_pdf:
                        return stats, n_error, n_success
                except:
                    print("not successful!")
                    n_error += 1

    return stats, n_error, n_success

# PDF Creation Date Converter (from PDF format to datetime)
# https://stackoverflow.com/questions/16503075/convert-creationtime-of-pdf-to-a-readable-format-in-python
from datetime import datetime
from time import mktime, strptime


def pdf_date_format_to_datetime(str):
    datestring = str[2:-7]
    ts = strptime(datestring, "%Y%m%d%H%M%S")
    dt = datetime.fromtimestamp(mktime(ts))
    return dt