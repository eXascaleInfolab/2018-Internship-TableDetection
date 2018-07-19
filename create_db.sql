DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS Users;
DROP TABLE IF EXISTS Crawls;


CREATE TABLE Users
(
	id INT(11) AUTO_INCREMENT PRIMARY KEY, 
	name VARCHAR(100), 
	email VARCHAR(100), 
	username VARCHAR(30), 
	password VARCHAR(100), 
	register_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);


CREATE TABLE Crawls
(
    cid INT(11) AUTO_INCREMENT PRIMARY KEY,
    crawl_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP UNIQUE,
    pdf_crawled INT(11),
    pdf_processed INT(11),
    process_errors INT(11),
    domain VARCHAR(100),
    url LONGTEXT,
    hierarchy LONGTEXT,
    stats LONGTEXT,
    crawl_total_time INT(11),
    proc_total_time INT(11)
);
