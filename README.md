# Confluence Tree Builder
## The script takes a tree of folders and publishes to the desired conflence host
***
***Tested on Confluence server and Data Center 7.12***
***
### First Run:
- Run ` pip install -r requirements.txt` to install dependencies
- Run with `--init-db` to get all the live pages on the confluence server and handle pages with the same name

### Arguments:
- `-h ` or `--help` to get help
- `--init-db` to initialize the database
- `--reinit-db` to re-initialize the database

### Constants
- `host` - host url
- `space_key` - the key of the relevant space in confluence
- `path` - relative or absolute path of the base folder of the tree
- `root_page_on_confluence` - the root of the tree on the confluence environment. leave blank if you want the tree to a root directory.
- `db` - name of the json file which stores the page names on the relative space
- `limit` - the max pages to pull per query