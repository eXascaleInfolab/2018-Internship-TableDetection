import os
import json


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


# finds the number of files in given path
def path_number_of_files(path):
    n_files = sum([len(files) for r, d, files in os.walk(path)])
    # TODO quickly check if pdf file or not !!!!!
    return n_files


# TODO write a Bottom up or DP method to make it faster ! (ask Akansha)



