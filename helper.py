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

    d = {'name': os.path.basename(p)}
    if os.path.isdir(p):
        d['type'] = "directory"
        d['children'] = [path_dict(os.path.join(p, x)) for x in os.listdir(p)]
        d['npdf'] = path_number_of_files(p) # Really bad, but quick way out
    else:
        d['type'] = "file"
        d['npdf'] = 1 #TODO check if pdf file or not !!

    return d


# TODO write a Bottom up or DP method to make it faster ! (ask Akansha)
# finds the number of files in given path
def path_number_of_files(path):
    n_files = sum([len(files) for r, d, files in os.walk(path)])
    # TODO quickly check if pdf file or not !!!!!
    return n_files


def pdf_stats(path):
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
                    table_stats = {'small-tables': 0, 'medium-tables': 0, 'large-tables': 0}

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
                                table_stats['small-tables'] += 1
                            elif rows <= MEDIUM_TABLE_LIMIT:
                                table_stats['medium-tables'] += 1
                            else:
                                table_stats['large-tables'] += 1

                    # STEP 4: save stats
                    stats[fileName] = (n_pages, n_table_pages, n_table_rows, table_stats) # FIXME use fileName or relFile ?
                    print("Tabula Conversion done for %s" % (fileName,))
                    n_success = n_success + 1
                except:
                    print("not successful!")
                    n_error += 1

    return stats, n_error, n_success

