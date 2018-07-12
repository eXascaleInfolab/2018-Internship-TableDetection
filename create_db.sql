DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS Users;
DROP TABLE IF EXISTS Crawls;


CREATE TABLE users
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
    crawl_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP PRIMARY KEY,
    pdf_crawled INT(11),
    pdf_processed INT(11),
    domain VARCHAR(100),
    url VARCHAR(100),
    hierarchy LONGTEXT,
    stats LONGTEXT
);
