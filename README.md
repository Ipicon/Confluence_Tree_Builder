# Confluence Tree Builder

## The script takes a tree of folders and publishes to the desired confluence host

***
***Tested on Confluence server and Data Center 7.12***
***

### First Run:

- Run ` pip install -r requirements.txt` to install dependencies
- ***DEPRECATED*** Run with `--init-db` to get all the live pages on the confluence server and handle pages with the
  same name
- No need for anything else 😊, once the script sees a page which already exists - it automatically retries with a
  higher occurrences index

### Arguments:

- `-h ` or `--help` to get help
- `--use-link` to post attachments as hyperlinks
- `--attachment-label ` by default there are no labels to the attachments. use this flag to enable them.
- ***DEPRECATED*** `--init-db` to initialize the database

### Constants

- `host` - host url
- `space_key` - the key of the relevant space in confluence
- `path` - relative or absolute path of the base folder of the tree
- `root_page_on_confluence` - the root of the tree on the confluence environment. leave blank if you want the tree to a
  root directory.
- `db` - name of the json file which stores the page names on the relative space
- `log_path` - name or path to the log file
- `limit` - the max pages to pull per query
- `max_attachment_size` - the max file size in MB