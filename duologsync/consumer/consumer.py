"""
Definition of the Consumer class
"""

import sys
import json
import logging
from duologsync.util import update_log_checkpoint

class Consumer():
    """
    Read logs from a queue shared with a producer object and write those logs
    somewhere using the write object passed. Additionally, once logs have been
    written successfully, take the latest log_offset - also shared with the
    Producer pair - and save it to a checkpointing file in order to recover
    progress if a crash occurs.
    """

    def __init__(self, log_queue, log_type, producer, writer):
        self.log_queue = log_queue
        self.log_type = log_type
        self.producer = producer
        self.writer = writer
        self.log_offset = None

    async def consume(self):
        """
        Consumer that will consume data from a queue shared with a producer
        ovject. Data from the queue is then sent over a configured transport
        protocol to respective SIEMs or servers.
        """
        while True:
            logging.info("%s consumer: waiting for logs from producer",
                         self.log_type)

            # Call unblocks only when there is an element in the queue to get
            logs = await self.log_queue.get()
            logging.info("%s consumer: received %d logs from producer",
                         self.log_type, len(logs))

            # Keep track of the latest log written in the case that a problem
            # occurs in the middle of writing logs
            last_log_written = None

            try:
                logging.info("%s consumer: writing logs", self.log_type)
                for log in logs:
                    self.writer.write(json.dumps(log).encode() + b'\n')
                    await self.writer.drain()
                    last_log_written = log

                # All the logs were written successfully
                last_log_written = None
            except Exception as error:
                logging.error("Failed to write data to transport: %s", error)
                sys.exit(1)
            finally:
                if last_log_written is None:
                    logging.info("%s consumer: successfully wrote all logs",
                                 self.log_type)
                else:
                    logging.warning("%s consumer: failed to write some logs",
                                    self.log_type)

                self.log_offset = self.producer.get_log_offset(last_log_written)
                logging.info("%s consumer: saving latest log offset to a "
                             "checkpointing file", self.log_type)
                update_log_checkpoint(self.log_type, self.log_offset)
