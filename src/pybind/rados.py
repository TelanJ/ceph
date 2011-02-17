"""librados Python ctypes wrapper
Copyright 2011, Hannu Valtonen <hannu.valtonen@ormod.com>
"""
from ctypes import CDLL, c_char_p, c_size_t, c_void_p,\
    create_string_buffer, byref, Structure, c_uint64, pointer
import errno
import time

class Error(Exception):
    def __init__(self, code):
        self.code = code
    def __repr__(self):
        return ("rados.Error(code=%d)" % self.code)

class PermissionError(Exception):
    pass

class ObjectNotFound(Exception):
    pass

class ObjectExists(Exception):
    pass

class IOError(Exception):
    pass

class NoSpace(Exception):
    pass

class IncompleteWriteError(Exception):
    pass

class PoolStateError(Exception):
    pass

class ObjectStateError(Exception):
    pass

def make_ex(ret, msg):
    ret = abs(ret)
    if (ret == errno.EPERM):
        return PermissionError(msg)
    elif (ret == errno.ENOENT):
        return ObjectNotFound(msg)
    elif (ret == errno.EIO):
        return IOError(msg)
    elif (ret == errno.ENOSPC):
        return NoSpace(msg)
    elif (ret == errno.EEXIST):
        return ObjectExists(msg)
    else:
        return Error(msg + (": error code %d" % ret))

class rados_pool_stat_t(Structure):
    _fields_ = [("num_bytes", c_uint64),
                ("num_kb", c_uint64),
                ("num_objects", c_uint64),
                ("num_object_clones", c_uint64),
                ("num_object_copies", c_uint64),
                ("num_objects_missing_on_primary", c_uint64),
                ("num_objects_unfound", c_uint64),
                ("num_objects_degraded", c_uint64),
                ("num_rd", c_uint64),
                ("num_rd_kb", c_uint64),
                ("num_wr", c_uint64),
                ("num_wr_kb", c_uint64)]

class Rados(object):
    """librados python wrapper"""
    def __init__(self):
        self.librados = CDLL('librados.so')
        ret = self.librados.rados_initialize(None)
        if ret != 0:
            raise Error("rados_initialize failed with error code: %d" % ret)
        self.initialized = True

    def __del__(self):
        if (self.__dict__.has_key("initialized") and self.initialized == True):
            self.librados.rados_deinitialize()

    def create_pool(self, pool_name):
        ret = self.librados.rados_create_pool(c_char_p(pool_name))
        if ret < 0:
            raise make_ex(ret, "error creating pool '%s'" % pool_name)

    def open_pool(self, pool_name):
        pool = c_void_p()
        ret = self.librados.rados_open_pool(c_char_p(pool_name), byref(pool))
        if ret < 0:
            raise make_ex(ret, "error opening pool '%s'" % pool_name)
        return Pool(pool_name, self.librados, pool)

class Pool(object):
    """Pool object"""
    def __init__(self, name, librados, pool):
        self.name = name
        self.librados = librados
        self.pool = pool
        self.state = "open"

    def check_pool_state(self):
        if self.state != "open":
            raise PoolStateError("The pool is %s" % self.state)

    def get_object(self, key):
        self.check_pool_state()
        return Object(self, key)

    def write(self, key, string_to_write, offset = 0):
        self.check_pool_state()
        length = len(string_to_write)
        ret = self.librados.rados_write(self.pool, c_char_p(key),
                    c_size_t(offset), c_char_p(string_to_write),
                    c_size_t(length))
        if ret == length:
            return ret
        elif ret < 0:
            raise make_ex(ret, "Pool.write(%s): failed to write %s" % \
                (self.name, key))
        elif ret < length:
            raise IncompleteWriteError("Wrote only %ld/%ld bytes" % (ret, length))
        else:
            raise make_ex("Pool.write(%s): logic error: rados_write \
returned %d, but %d was the maximum number of bytes it could have \
written." % (self.name, ret, length))

    def read(self, key, offset = 0, length = 8192):
        self.check_pool_state()
        ret_buf = create_string_buffer(length)
        ret = self.librados.rados_read(self.pool, c_char_p(key), c_size_t(offset),
                                        ret_buf, c_size_t(length))
        if ret < 0:
            raise make_ex("Pool.read(%s): failed to read %s" % (self.name, key))
        return ret_buf.value

    def get_stats(self):
        self.check_pool_state()
        stats = rados_pool_stat_t()
        ret = self.librados.rados_stat_pool(self.pool, byref(stats))
        if ret < 0:
            raise make_ex(ret, "Pool.get_stats(%s): get_stats failed" % self.name)
        return {'num_bytes': stats.num_bytes,
                'num_kb': stats.num_kb,
                'num_objects': stats.num_objects,
                'num_object_clones': stats.num_object_clones,
                'num_object_copies': stats.num_object_copies,
                "num_objects_missing_on_primary": stats.num_objects_missing_on_primary,
                "num_objects_unfound": stats.num_objects_unfound,
                "num_objects_degraded": stats.num_objects_degraded,
                "num_rd": stats.num_rd,
                "num_rd_kb": stats.num_rd_kb,
                "num_wr": stats.num_wr,
                "num_wr_kb": stats.num_wr_kb }

    def remove_object(self, key):
        self.check_pool_state()
        ret = self.librados.rados_remove(self.pool, c_char_p(key))
        if ret < 0:
            raise make_ex(ret, "Failed to remove '%s'" % key)
        return True

    def stat(self, key):
        self.check_pool_state()
        """Stat object, returns, size/timestamp"""
        psize = c_uint64()
        pmtime = c_uint64()

        ret = self.librados.rados_stat(self.pool, c_char_p(key), pointer(psize),
                                        pointer(pmtime))
        if ret < 0:
            raise make_ex(ret, "Failed to stat %r" % key)
        return psize.value, time.localtime(pmtime.value)

    def get_xattr(self, key, xattr_name):
        self.check_pool_state()
        ret_length = 4096
        ret_buf = create_string_buffer(ret_length)
        ret = self.librados.rados_getxattr(self.pool, c_char_p(key),
                    c_char_p(xattr_name), ret_buf, c_size_t(ret_length))
        if ret < 0:
            raise make_ex(ret, "Failed to get xattr %r" % xattr_name)
        return ret_buf.value

    def set_xattr(self, key, xattr_name, xattr_value):
        self.check_pool_state()
        ret = self.librados.rados_setxattr(self.pool, c_char_p(key),
                    c_char_p(xattr_name), c_char_p(xattr_value),
                    c_size_t(len(xattr_value)))
        if ret < 0:
            raise make_ex(ret, "Failed to set xattr %r" % xattr_name)
        return True

    def rm_xattr(self, key, xattr_name):
        self.check_pool_state()
        ret = self.librados.rados_rmxattr(self.pool, c_char_p(key), c_char_p(xattr_name))
        if ret < 0:
            raise make_ex(ret, "Failed to delete key %r xattr %r" %
                (key, xattr_name))
        return True

    def delete(self):
        self.check_pool_state()
        ret = self.librados.rados_delete_pool(self.pool)
        if ret < 0:
            raise make_ex(ret, "error deleting pool '%s'" % pool_name)
        self.state = "deleted"

    def close(self, pool):
        self.check_pool_state()
        ret = self.librados.rados_close_pool(pool)
        if ret < 0:
            raise make_ex(ret, "error closing pool '%s'" % pool)
        self.state = "closed"


class Object(object):
    """Rados object wrapper, makes the object look like a file"""
    def __init__(self, pool, key):
        self.key = key
        self.pool = pool
        self.offset = 0
        self.state = "exists"

    def check_object_state(self):
        if self.state != "exists":
            raise ObjectStateError("The object is %s" % self.state)

    def read(self, length = 1024*1024):
        self.check_object_state()
        ret = self.pool.read(self.key, self.offset, length)
        self.offset += len(ret)
        return ret

    def write(self, string_to_write):
        self.check_object_state()
        ret = self.pool.write(self.key, string_to_write, self.offset)
        self.offset += ret
        return ret

    def remove(self):
        self.check_object_state()
        self.pool.remove_object(self.key)
        self.state = "removed"

    def stat(self):
        self.check_object_state()
        return self.pool.stat(self.key)

    def seek(self, position):
        self.check_object_state()
        self.offset = position

    def get_xattr(self, xattr_name):
        self.check_object_state()
        return self.pool.get_xattr(self.key, xattr_name)

    def set_xattr(self, xattr_name, xattr_value):
        self.check_object_state()
        return self.pool.set_xattr(self.key, xattr_name, xattr_value)

    def rm_xattr(self, xattr_name):
        self.check_object_state()
        return self.pool.rm_xattr(self.key, xattr_name)
