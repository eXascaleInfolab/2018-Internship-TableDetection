from helper import pdf_stats


stats, n_error, n_success = pdf_stats("data/www.bsv.admin.ch")




print("Number errors: %d" % (n_error,))
print("Number successes: %d" % (n_success,))
print(stats)