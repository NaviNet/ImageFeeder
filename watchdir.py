# -*- coding: utf-8 -*-

from distutils import dir_util
import os
import Queue
import shutil
import threading
import time

from watchdog import events
from watchdog import observers

_WATCHER_THREADS = []
_STOP_QUEUES = []
PROCESSING_DIR_NAME = 'IN-PROGRESS'
SUCCESS_DIR_NAME = 'DONE'
FAILURE_DIR_NAME = 'FAILED'


class CreationEventHandler(events.FileSystemEventHandler):
    """Event handler for moving new files.
    """

    def __init__(self, _=None):
        """Initializes the event handler.
        """
        self._backlog = Queue.Queue()
        thread = threading.Thread(target=self._process)
        thread.daemon = True
        thread.start()

    def on_created(self, event):
        """Queues a new file for processing.

        Does not queue directories. Moves files to a processing
        directory.

        Args:
            event: The file system event.
        """
        src_path = event.src_path
        if os.path.isfile(src_path):
            head, tail = os.path.split(src_path)
            new_path = os.path.join(os.path.dirname(head),
                                    PROCESSING_DIR_NAME, tail)
            self._mv_f(src_path, new_path)
            self._backlog.put(new_path)

    def _mv_f(self, src, dst):
        """Moves a regular file.

        Overwrites the destination if it exists but is not a directory.

        Args:
            src: The path of the source file.
            dst: The path of the destination.
        """
        while os.path.exists(dst):
            try:
                os.remove(dst)
            except:
                pass
        while os.path.exists(dst):
            time.sleep(0.1)  # Wait for the removal to complete
        os.rename(src, dst)
        while os.path.exists(src):
            time.sleep(0.1)

    def _process(self):
        """Process the backlog.
        """
        raise NotImplementedError


def _make_empty_directory(path):
    """Clears a directory or deletes a regular file.

    Deletes whatever the path refers to (if anything) and creates an
    empty directory at that path. The parent of the directory to be
    created must already exist.

    Args:
        path: The path to make point to an empty directory.
    """
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)
    os.mkdir(path)


def watch(path, context_manager):
    """Watches a directory for files to send in another thread.

    The event handler's initializer must be able to take exactly one
    argument, a Queue to fill to stop watching.

    Args:
        path: The name of the directory to watch, without a trailing
            directory separator.
        context_manager: A context manager which produces an event
            handler.
    """
    # If path has a trailing directory separator, dirname won't work
    parent = os.path.dirname(path)
    for new_dir_name in [PROCESSING_DIR_NAME, SUCCESS_DIR_NAME,
                         FAILURE_DIR_NAME]:
        _make_empty_directory(os.path.join(parent, new_dir_name))
    stop_queue = Queue.Queue()
    _STOP_QUEUES.append(stop_queue)
    thread = threading.Thread(target=_watch,
                              args=(path, context_manager, stop_queue))
    thread.start()
    _WATCHER_THREADS.append(thread)


def _watch(path, context_manager, stop_queue):
    """Watches a directory for files to send.

    Args:
        path: The name of the directory to watch.
        context_manager: A context manager which produces an event
            handler.
        stop_queue: A Queue to fill to stop watching. It is passed as
            the only argument to the event handler's initializer.
    """
    with context_manager(stop_queue) as event_handler:
        observer = observers.Observer()
        observer.schedule(event_handler, path)
        observer.start()
        success = stop_queue.get()
        observer.stop()
        observer.join()
        src = os.path.join(os.path.dirname(path), PROCESSING_DIR_NAME)
        dst = os.path.join(os.path.dirname(path),
                           SUCCESS_DIR_NAME if success else FAILURE_DIR_NAME)
        dir_util.remove_tree(dst)
        dir_util.copy_tree(src, dst)
        for base_name in os.listdir(src):
            path = os.path.join(src, base_name)
            if os.path.isfile(path):
                os.remove(path)


def stop_watching():
    """Stops watching all directories.
    """
    for stop_queue in _STOP_QUEUES:
        stop_queue.put(False)
    for thread in _WATCHER_THREADS:
        thread.join()