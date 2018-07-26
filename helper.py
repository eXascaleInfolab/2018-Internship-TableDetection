import os
import tabula
import PyPDF2
import datetime
from time import mktime, strptime
from requests import post
import requests



# CONSTANTS



# Create a json string for given path
# source: https://stackoverflow.com/questions/25226208/represent-directory-tree-as-json
def path_dict(path):
    p = path
    name = os.path.basename(p)

    # SMALL CONSTRUCT TO SHORTEN HIERARCHY
    # Check if there is only one directory inside
    while os.path.isdir(p) and len(os.listdir(p)) == 1:
        # If that's the case then append it to the name and go further inside
        sole_dir = os.listdir(p)[0]
        name = name + "/" + sole_dir
        p = os.path.join(p, sole_dir)

    # ORIGINAL CONSTRUCT
    d = {'name': name}
    if os.path.isdir(p):
        d['type'] = "directory"
        d['children'] = [path_dict(os.path.join(p, x)) for x in os.listdir(p)]
        d['npdf'] = path_number_of_files(p) # Really bad, but quick way out
    else:
        d['type'] = "file"
        if ".pdf" in p:
            d['npdf'] = 1
            d['url'] = p[5:] # FIXME remove if link not used
        else:
            d['npdf'] = 0
    return d


# TODO write a Bottom up or DP method to make it faster ! (ask Akansha)
# finds the number of files in given path
def path_number_of_files(path):
    n_files = sum([len(list(filter(lambda f: ".pdf" in f, files))) for r, d, files in os.walk(path)])
    return n_files


# Returns the size of the directory in bytes
def dir_size(path):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            total_size += os.path.getsize(fp)
    return total_size


# Uses Tabula to detect and extract tables from the pdf's
# INPUT: path containing pdf's and the maximal number of pdf to analyse
def pdf_stats(path, n_pdf, post_url):
    stats = {}

    # Keep track of successful and unsuccessful files
    n_success = 0
    n_error = 0

    for dir_, _, files in os.walk(path):
        for fileName in files:
            if ".pdf" in fileName:

                # Check if enough pdf already processed
                if n_success + n_error >= n_pdf:
                    return stats, n_error, n_success

                print("Number errors: %d" % (n_error,))
                print("Number successes: %d" % (n_success,))
                print(stats)

                try:
                    # Get file location
                    rel_file = os.path.join(dir_, fileName)

                    # STEP 0: set all counter to 0
                    n_table_pages = 0
                    n_table_rows = 0
                    table_sizes = {'small': 0, 'medium': 0, 'large': 0}

                    # STEP 1: count total number of pages
                    pdf_file = PyPDF2.PdfFileReader(open(rel_file, mode='rb'))
                    n_pages = pdf_file.getNumPages()

                    # STEP 2: run TABULA to extract all tables into one dataframe
                    df_array = tabula.read_pdf(rel_file, pages="all", multiple_tables=True)

                    # STEP 3: count number of rows in each dataframe
                    for df in df_array:
                        rows = df.shape[0]
                        n_table_rows += rows
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
                    n_success += 1

                    # STEP 5: Send message asynchronously
                    post(post_url, json={'event':'my_response', 'data':
                        {'data': 'I successfully performed table detection', 'success': n_success, 'count': 1}})

                # FIXME more specific,
                # FIXME otherwise it enters infinite loop if file not found for example / bad url was given
                except:
                    print("ERROR: Tabula Conversion failed for %s" % (fileName,))
                    n_error += 1

    return stats, n_error, n_success


# PDF Creation Date Converter (from PDF format to datetime)
# https://stackoverflow.com/questions/16503075/convert-creationtime-of-pdf-to-a-readable-format-in-python
def pdf_date_format_to_datetime(str):
    datestring = str[2:-7]
    try :
        ts = strptime(datestring, "%Y%m%d%H%M%S")
        dt = datetime.datetime.fromtimestamp(mktime(ts))
    except ValueError:
        print("Unable to convert time for string: " + str)
        dt = datetime.datetime.strptime("01/01/1970", '%m/%d/%Y')
    return dt


# Checks if a URL exists
def exists(url):
    try:
        r = requests.head(url)
        return r.status_code == requests.codes.ok
    except:
        return False

