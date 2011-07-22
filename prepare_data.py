import array
import datetime
import itertools
import os.path
import sys
import struct

# TODO user optionParser
options = dict()
for arg in sys.argv[1:]:
  try:
    key, value = arg.strip().split('=')
    key = key[2:].replace('-', '_')
    options[key] = value
  except ValueError: pass

try:
  fin = open(options['infile'], 'r')
  infile_size = os.path.getsize(options['infile'])
  print "File size: %s" % infile_size
except KeyError:
  print "infile '%s' does not exist"
  sys.exit(-1)

outfilename = options.get('outfile', 'set_arrays.bin')
if os.path.exists(outfilename):
  raise Exception("%s already exists, please remove first" % outfilename)

# helper function to turn an iterable into a list of tuples
in_pairs = lambda xs: [tuple(xs[i:i+2]) for i in range(0, len(xs), 2)]

BUFFERSIZE = 1024 * 64
SIZEOFINT = 4
INTCOUNT = BUFFERSIZE / SIZEOFINT
print "Reading in %d integers at a time" % INTCOUNT

def fill_buffer(fin, BUFFERSIZE):
  """Read `INTCOUNT` integers from file handle `fin` and return array of ints""" 
  set_id_array = array.array('I')
  try:
    set_id_array.fromfile(fin, (INTCOUNT))
  except EOFError: pass
  return map(int, set_id_array)

def enumerate_set_ids(fin, progress_func=lambda x: 0):
  """Return list of integers for set_ids from a file handle. This funtion
  resets the file position. Assumes the input is (user_id, set_id) * N in
  binary.
  """
  fin.seek(0)
  set_ids = set()
  for readbytes in itertools.count(start=0, step=BUFFERSIZE):
    ints = fill_buffer(fin, BUFFERSIZE)
    # grab every other integer, skipping the first one
    new_set_ids = (ints[i+1] for i in xrange(0, len(ints), 2))
    set_ids.update(set(new_set_ids))
    progress_func(readbytes, mb=100)
    if len(ints) != (BUFFERSIZE / SIZEOFINT):
      return tuple(set_ids)

def progress_func(readbytes, mb=100):
  if readbytes % (BUFFERSIZE * 16 * mb) == 0:
    print "%d / %d bytes read, %.2f%% complete" % (
      readbytes, infile_size, 100 * readbytes / float(infile_size)
    )

# generate or load set_ids
set_id_filename = options.get('set_id_filename', 'set_ids.txt')
if not os.path.exists(set_id_filename):
  print "Enumerating set_ids from file"
  set_ids = enumerate_set_ids(fin, progress_func)
  with open(set_id_filename, 'w+') as fh:
    #TODO would love a comment on this -- newlines force the kludge
    fh.writelines("%s\n" % l for l in set_ids)
else:
  print "Loading set_ids from file"
  with open(set_id_filename) as fh:
    set_ids = tuple(map(int, fh))
print "%d unique set_ids in file" % len(set_ids)

set_array_offsets = dict()

SEGSIZE = 10000
offset = int(options.get('offset', 0))
print "Using set_ids offset: %d" % offset
for set_id_segment in (set_ids[i:i+SEGSIZE] for i in xrange(offset, len(set_ids), SEGSIZE)):
  print "Starting segment %d" % (int(set_ids.index(set_id_segment[0])) / SEGSIZE)

  # reset data structures
  set_membership = dict((set_id, []) for set_id in set_id_segment)
  set_id_segment_set = set(set_id_segment)
  fin.seek(0) # reset file

  # read entire data file until we're out
  try:
    for readbytes in itertools.count(start=0, step=BUFFERSIZE):
      pairs = in_pairs(fill_buffer(fin, BUFFERSIZE))
      for user_id, set_id in pairs:
        if set_id in set_id_segment_set:
          set_membership[set_id].append(user_id)
      progress_func(readbytes, mb=100)
      if len(pairs) != (BUFFERSIZE / SIZEOFINT / 2):
        raise EOFError
  except EOFError:
    print "Hit EOF"
    pass
  total = sum(len(user_ids) for user_ids in set_membership.values())
  print "Total user_ids: %d" % total
  print "Biggest set has %d users" % max(len(user_ids) for user_ids in set_membership.values())

  small_sets = 0
  with open(outfilename, 'ab+') as fout:
    for set_id, user_ids in set_membership.iteritems():
      # drop one member sets
      if len(user_ids) <= 1:
        small_sets += 1
        continue

      # add stop integer
      user_ids += [0]

      set_array_offsets[set_id] = file_offset = fout.tell()
      print "Offset %d, set_id %s, about to write %d bytes" % (
        file_offset, set_id, len(user_ids * 4)
      )
      user_id_array = array.array('I')
      user_id_array.fromlist(user_ids)
      user_id_array.tofile(fout)
      print "Offset %d, set_id %s, %d actual bytes written" % (
        fout.tell(), set_id, fout.tell() - file_offset
      )
    print "%d bytes written to %s" % (fout.tell(), outfilename)
  print "Skipped %d sets with 1 member" % small_sets

# sanity check: does the visual output seem right?
# integrity checks:
#   * the byte before each offset should be 0 to indicate the end of the
#     previous user_id array
#TODO more integrity checks
with open(outfilename, 'rb') as set_array_bin:
  for set_id, offset in set_array_offsets.iteritems():
    print '%d: %d' % (set_id, offset)

    if offset - SIZEOFINT < 0: continue
    set_array_bin.seek(offset - SIZEOFINT)
    zero_array = array.array('I')
    zero_array.fromfile(set_array_bin, 1)
    assert zero_array[0] == 0

max_set_id = max(map(int, set_array_offsets.keys()))
print "max set_id: %d" % max_set_id


index_filename = options.get('indexfile', 'set_array_index.bin')
with open(index_filename, 'wb') as indexfile:
  index_list = [
    set_array_offsets.get(set_id, 0)
    for set_id
    in xrange(max(set_array_offsets.keys()))
  ]
  index_array = array.array('I')
  index_array.fromlist(index_list)
  index_array.tofile(indexfile)
