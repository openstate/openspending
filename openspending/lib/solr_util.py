'''\
Helper methods for using Solr.
'''

import datetime
import logging
import json
from unicodedata import category

from solr import SolrConnection, SolrException

from openspending import model
from openspending.lib.util import flatten

log = logging.getLogger(__name__)

url = 'http://localhost:8983/solr'
http_user = None
http_pass = None

_client = None

# Solr connection singleton
_solr = None


# Helper class to represent the UTC timezone.
class UTC(datetime.tzinfo):

    def utcoffset(self, dt):
        return datetime.timedelta(0)

    def dst(self, dt):
        return datetime.timedelta(0)

    def tzname(self, dt):
        return "UTC"

    __reduce__ = object.__reduce__


def configure(config=None):
    global url
    global http_user
    global http_pass

    if not config:
        config = {}

    url = config.get('openspending.solr.url', url)
    http_user = config.get('openspending.solr.http_user', http_user)
    http_pass = config.get('openspending.solr.http_pass', http_pass)


def get_connection():
    """Returns the global Solr connection, or creates one, as required."""
    global _solr

    if _solr:
        return _solr

    _solr = SolrConnection(url,
                           http_user=http_user,
                           http_pass=http_pass)

    return _solr


def drop_index(dataset_name):
    solr = get_connection()
    solr.delete_query('dataset:%s' % dataset_name)
    solr.commit()


def dataset_entries(dataset_name):
    solr = get_connection()
    res = solr.raw_query(q='*:*', fq='dataset:"%s"' % dataset_name, rows=0, wt='json')
    res = json.loads(res)
    return res.get('response', {}).get('numFound')


def extend_entry(entry, dataset):
    entry['dataset'] = dataset.name
    entry['dataset.id'] = dataset.id
    entry = flatten(entry)
    entry['_id'] = dataset.name + '::' + unicode(entry['id'])
    for k, v in entry.items():
        if k.endswith(".taxonomy") or k.endswith('.color'):
            continue
        # this is similar to json encoding, but not the same.
        if isinstance(v, datetime.datetime) and not v.tzinfo:
            entry[k] = datetime.datetime(v.year, v.month, v.day, v.hour,
                                         v.minute, v.second, tzinfo=UTC())
        elif '.' in k and isinstance(v, (list, tuple)):
            entry[k] = " ".join([unicode(vi) for vi in v])
        else:
            entry[k] = _safe_unicode(entry[k])
        if k.endswith(".name"):
            vk = k[:len(k) - len(".name")]
            entry[vk] = v
        if k.endswith(".label"):
            entry[k + "_facet"] = entry[k]
    return entry


def build_index(dataset_name):
    solr = get_connection()
    dataset_ = model.Dataset.by_name(dataset_name)
    if dataset_ is None:
        raise ValueError("No such dataset: %s" % dataset_name)
    buf = []
    for i, entry in enumerate(dataset_.entries()):
        ourdata = extend_entry(entry, dataset_)
        #from pprint import pprint
        #pprint(ourdata)
        buf.append(ourdata)
        if i and i % 1000 == 0:
            solr.add_many(buf)
            solr.commit()
            log.info("Indexed %d entries", i)
            buf = []
    solr.add_many(buf)
    solr.commit()
    dataset_.updated_at = datetime.datetime.utcnow()
    model.db.session.commit()


def build_all_index():
    for dataset in model.db.session.query(model.Dataset):
        try:
            count = len(dataset)
        except:
            count = 0
        if count is 0:
            continue
        log.info("Indexing: %s (%s entries)", dataset.name, count)
        drop_index(dataset.name)
        build_index(dataset.name)

def _safe_unicode(s):
    if not isinstance(s, basestring):
        return s
    return u"".join([c for c in unicode(s) if not category(c)[0] == 'C'])
