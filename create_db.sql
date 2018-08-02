DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS Users;
DROP TABLE IF EXISTS Crawlfiles;
DROP TABLE IF EXISTS Crawls;
DROP TABLE IF EXISTS Files;



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
    disk_size BIGINT UNSIGNED,
    url LONGTEXT,
    hierarchy LONGTEXT,
    crawl_total_time BIGINT,
    proc_total_time BIGINT
);


CREATE TABLE Files
(
	fid INT(11) AUTO_INCREMENT PRIMARY KEY,
	processing_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
	url LONGTEXT,
	stats LONGTEXT
	
);


CREATE TABLE Crawlfiles
(
	fid INT(11),
	cid INT(11),
	PRIMARY KEY(fid, cid),
	FOREIGN KEY (fid)
      	REFERENCES Files(fid)
	ON DELETE CASCADE,
	FOREIGN KEY (cid)
      	REFERENCES Crawls(cid)
	ON DELETE CASCADE
);
