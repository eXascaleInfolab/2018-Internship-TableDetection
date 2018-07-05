import os
import json


# Create a json string for given path
# source: https://stackoverflow.com/questions/25226208/represent-directory-tree-as-json
def path_stats(path):
    p = path.encode('cp1252')

    d = {'name': os.path.basename(p)}
    if os.path.isdir(p):
        d['type'] = "directory"
        d['children'] = [path_stats(os.path.join(p, x)) for x in os.listdir(p)]
    else:
        d['type'] = "file"

    return d


# finds the number of files in given path
def path_file_number(path):
    n_file = 0
    if os.path.isdir(path):
        for x in os.listdir(path):
            n_file += path_file_number(os.path.join(path, x))
    else:
        n_file += 1

    # FIXME this is not precise when 0 files present

    return n_file
