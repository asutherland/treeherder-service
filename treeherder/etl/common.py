from collections import defaultdict
import hashlib
import urllib2
import simplejson as json
import time

from django.core.urlresolvers import reverse
from django.conf import settings

class JobDataError(ValueError):
    pass


class JobData(dict):
    """
    Encapsulates data access from incoming test data structure.

    All missing-data errors raise ``JobDataError`` with a useful
    message. Unlike regular nested dictionaries, ``JobData`` keeps track of
    context, so errors contain not only the name of the immediately-missing
    key, but the full parent-key context as well.
    """

    def __init__(self, data, context=None):
        """Initialize ``JobData`` with a data dict and a context list."""
        self.context = context or []
        super(JobData, self).__init__(data)

    @classmethod
    def from_json(cls, json_blob):
        """Create ``JobData`` from a JSON string."""
        try:
            data = json.loads(json_blob)
        except ValueError as e:
            raise JobDataError("Malformed JSON: {0}".format(e))
        return cls(data)

    def __getitem__(self, name):
        """Get a data value, raising ``JobDataError`` if missing."""
        full_context = list(self.context) + [name]

        try:
            value = super(JobData, self).__getitem__(name)
        except KeyError:
            raise JobDataError("Missing data: {0}.".format(
                "".join(["['{0}']".format(c) for c in full_context])))

        # Provide the same behavior recursively to nested dictionaries.
        if isinstance(value, dict):
            value = self.__class__(value, full_context)

        return value


def retrieve_api_content(url):
    req = urllib2.Request(url)
    req.add_header('Content-Type', 'application/json')
    conn = urllib2.urlopen(
        req,
        timeout=settings.TREEHERDER_REQUESTS_TIMEOUT
    )
    if conn.getcode() == 404:
        return None


def get_remote_content(url):
    """A thin layer of abstraction over urllib. """
    req = urllib2.Request(url)
    req.add_header('Accept', 'application/json')
    req.add_header('Content-Type', 'application/json')
    conn = urllib2.urlopen(
        req,
        timeout=settings.TREEHERDER_REQUESTS_TIMEOUT)

    if not conn.getcode() == 200:
        return None
    try:
        content = json.loads(conn.read())
    except:
        content = None
    finally:
        conn.close()

    return content


def lookup_revisions(revision_dict):
    """
    Retrieve a list of revision->resultset lookups
    """
    lookup = dict()
    for project, revisions in revision_dict.items():
        revision_set = set(revisions)
        endpoint = reverse('revision-lookup-list', kwargs={"project": project})
        # build the query string as a comma separated list of revisions
        q = ','.join(revision_set)
        url = "{0}/{1}/?revision={2}".format(
            settings.API_HOSTNAME.strip('/'),
            endpoint.strip('/'),
            q
        )

        content = get_remote_content(url)
        if content:
            lookup[project] = content
    return lookup


def generate_revision_hash(revisions):
    """Builds the revision hash for a set of revisions"""

    sh = hashlib.sha1()
    sh.update(
        ''.join(map(lambda x: str(x), revisions))
    )

    return sh.hexdigest()


def generate_job_guid(request_id, request_time, endtime=None):
    """Converts a request_id and request_time into a guid"""
    sh = hashlib.sha1()

    sh.update(str(request_id))
    sh.update(str(request_time))
    job_guid = sh.hexdigest()

    # for some jobs (I'm looking at you, ``retry``) we need the endtime to be
    # unique because the job_guid otherwise looks identical
    # for all retries and the complete job.  The ``job_guid`` needs to be
    # unique in the ``objectstore``, or it will skip the rest of the retries
    # and/or the completed outcome.
    if endtime:
        job_guid = "{0}_{1}".format(job_guid, str(endtime)[-5:])
    return job_guid


def get_guid_root(guid):
    """Converts a job_guid with endtime suffix to normal job_guid"""
    if "_" in str(guid):
        return str(guid).split("_", 1)[0]
    return guid


def fetch_missing_resultsets(source, missing_resultsets, logger):
    """
    Schedules refetch of resultsets based on ``missing_revisions``
    """
    for k, v in missing_resultsets.iteritems():
        missing_resultsets[k] = list(v)

    logger.warn(
        "Found {0} jobs with missing resultsets.  Scheduling re-fetch: {1}".format(
            source,
            missing_resultsets
            )
         )
    from treeherder.etl.tasks.cleanup_tasks import fetch_missing_push_logs
    fetch_missing_push_logs.apply_async(args=[missing_resultsets])


def get_resultset(project, revisions_lookup, revision, missing_resultsets, logger):
    """
    Get the resultset out of the revisions_lookup for the given revision.

    This is a little complex due to our attempts to get missing resultsets
    in case we see jobs that, for one reason or another, we didn't get the
    resultset from json-pushes.

    This may raise a KeyError if the project or revision isn't found in the
    lookup..  This signals that the job should be skipped
    """

    resultset_lookup = revisions_lookup[project]
    try:
        resultset = resultset_lookup[revision]

        # we can ingest resultsets that are not active for various
        # reasons.  One would be that the data from pending/running/
        # builds4hr may have a bad revision (from the wrong repo).
        # in this case, we ingest the resultset as inactive so we
        # don't keep re-trying to find it when we hit jobs like this.
        # Or, the resultset could be inactive for other reasons.
        # Either way, we don't want to ingest jobs for it.
        if resultset.get("active_status", "active") != "active":
            logger.info(("Skipping job for non-active "
                         "resultset/revision: {0}").format(
                            revision))


    except KeyError as ex:
        # we don't have the resultset for this build/job yet
        # we need to queue fetching that resultset
        if revision not in ["Unknown", None]:
            missing_resultsets[project].add(revision)
        raise ex

    return resultset


def get_not_found_onhold_push(url, revision):
    return {
        "00001": {
            "date": int(time.time()),
            "changesets": [
                {
                    "node": revision,
                    "files": [],
                    "tags": [],
                    "author": "Unknown",
                    "branch": "default",
                    "desc": "Pushlog not found at {0}".format(url)
                }
            ],
            "user": "Unknown",
            "active_status": "onhold"
        }
    }