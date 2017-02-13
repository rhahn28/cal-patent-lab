#!/usr/bin/env python2
import json
import MySQLdb
import re
import signal
import sys

DB_HOST = "quicksand.ocf.berkeley.edu"
DB_USER = "***REMOVED***"
DB_PASSWORD = None  # Get this field from the user
DB_NAME = "***REMOVED***"


class DBPopulator:
    def __init__(self, host, username, password, db_name, table_name, batch_size=48):
        self.table_name = table_name
        self.batch_size = batch_size
        self.closed = False
        
        self.db_conn = MySQLdb.connect(host, username, password, db_name)
        self.cursor = self.db_conn.cursor()
        self.insert_queue = []
        
        # Get column names from DB
        self.cursor.execute("DESCRIBE {}".format(self.table_name))
        self.columns = [column_info[0] for column_info in self.cursor.fetchall()]
        self.single_placeholder = "(" + ",".join(["%s"] * len(self.columns)) + ")"
    
    
    def insert(self, line):
        if self.closed:
            raise ValueError("I/O operation on closed DB populator")
        self.insert_queue.append(line)
        if len(self.insert_queue) >= self.batch_size:
            self.flush()
    
    
    def flush(self):
        if self.closed:
            raise ValueError("I/O operation on closed DB populator")
        if len(self.insert_queue) == 0:
            return
        query_placeholder = ",".join([self.single_placeholder] * len(self.insert_queue))
        sql_query_tmpl = "INSERT INTO {} (" + ",".join(self.columns) + ") VALUES {}"
        sql_query = sql_query_tmpl.format(self.table_name, query_placeholder)
        
        # Flatten the insert queue
        data_values = []
        for line in self.insert_queue:
            for item in line:
                data_values.append(item)
        
        # Strip out any non-ASCII values
        for i in range(len(data_values)):
            if type(data_values[i]) in (str, unicode):
                data_values[i] = re.sub('[^\x00-\x7F]','', data_values[i])
        
        self.cursor.execute(sql_query, data_values)
        self.insert_queue = []
    
    
    def commit(self):
        if self.closed:
            raise ValueError("I/O operation on closed DB populator")
        try:
            self.db_conn.commit()
            return True
        except:
            self.db_conn.rollback()
            return False
    
    
    def close(self):
        self.flush()
        self.commit()
        self.db_conn.close()
        self.closed = True


def build_ptab_table_line(ptab_entry):
    line = [
        ptab_entry["trialNumber"],  # This field must not be null
        ptab_entry.get("patentNumber"),
        ptab_entry.get("invalidated"),
        ptab_entry.get("denied"),
        ptab_entry.get("filingDate"),
        ptab_entry.get("institutionDecisionDate"),
        ptab_entry.get("patentOwnerName"),
        ptab_entry.get("petitionerPartyName")
    ]
    return line


def build_patent_table_line(patent_id, patent_entry):
    line = [
        patent_id,
        patent_entry.get("filingDate"),
        patent_entry.get("issueDate"),
        patent_entry.get("artUnit"),
        patent_entry.get("examinerName")
    ]
    return line


def handle_ctrl_c(signal, frame):
    print("SIGINT caught, committing to DB and shutting down")
    status = commit_pending_db_data(db_conn)
    if not status:
        print("WARNING: error committing to DB")
    sys.exit(1)


def main():
    argv = sys.argv[1:]
    if len(argv) != 2:
        print("Usage: populate_db.py ptab_api_metadata_input "
              "patent_metadata_input")
        sys.exit(1)
    
    # Catch SIGINT (e.g. generated by Ctrl-C on the keyboard)
    signal.signal(signal.SIGINT, handle_ctrl_c)
    
    ptab_data_filename = argv[0]
    patent_filename = argv[1]
    
    ptab_data = json.load(open(ptab_data_filename))
    patent_data = json.load(open(patent_filename))
    
    # Prompt for database password
    global DB_PASSWORD
    print("Please enter the database password: ")
    DB_PASSWORD = sys.stdin.readline().strip()
    
    ptab_table_writer = DBPopulator(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, "ptab_cases")
    patent_table_writer = DBPopulator(DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, "patent_info")
    
    counter = 0
    num_lines = len(ptab_data)
    for entry in ptab_data:
        counter += 1
        line = build_ptab_table_line(entry)
        ptab_table_writer.insert(line)
        if counter & 0x1ff == 0:
            print("Inserting line {}/{}".format(counter, num_lines))
    ptab_table_writer.flush()
    ptab_table_writer.close()
    
    counter = 0
    num_lines = len(patent_data)
    for patent_id in patent_data:
        counter += 1
        entry = patent_data[patent_id]
        line = build_patent_table_line(patent_id, entry)
        patent_table_writer.insert(line)
        if counter & 0x1ff == 0:
            print("Inserting line {}/{}".format(counter, num_lines))
    patent_table_writer.flush()
    patent_table_writer.close()


if __name__ == "__main__":
    main()
