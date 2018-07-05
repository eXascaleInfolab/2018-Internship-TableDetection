var myHeading = document.querySelector('h1');
myHeading.textContent = 'Hello world!';


console.log("success so far");

var DirectoryStructureJSON = require('directory-structure-json');
var basepath = 'data/www.bar.admin.ch';
var fs = require('fs'); // you can select any filesystem as long as it implements the same functions that native fs uses.

myHeading.textContent = 'Still working world!';

DirectoryStructureJSON.getStructure(fs, basepath, function (err, structure, total) {
    if (err) console.log(err);

    console.log('there are a total of: ', total.folders, ' folders and ', total.files, ' files');
    console.log('the structure looks like: ', JSON.stringify(structure, null, 4));
});