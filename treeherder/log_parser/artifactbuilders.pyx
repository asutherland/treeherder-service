from .parsers import (ErrorParser, TinderboxPrintParser,
                      HeaderParser, StepParser, TalosParser)


class ArtifactBuilderBase(object):
    """
    Base class for all Buildbot log parsers.

    The child class will be designed to create a particular type of artifact.

    This class is called for each line of the log file, so it has no
    knowledge of the log file itself, as a whole.  It only, optionally, has
    the url to the log file to add to its own artifact.

    """
    MAX_LINE_LENGTH = 500

    def __init__(self, url=None):
        """
        Create the LogParser

        ``url`` - The url this log comes from.  It's optional, but it gets
                  added to the artifact.
        """
        self.artifact = {
            "logurl": url
        }
        self.lineno = 0
        self.parsers = []
        self.name = "Generic Artifact"

    def parse_line(self, line):
        """Parse a single line of the log."""

        """
        Talos data is stored in a json structure contained in
        a single line, if the MAX_LINE_LENGTH is applied the
        data structure could be truncated preventing it from
        being ingested.
        """
        if "TALOSDATA" not in line and 'TalosResult' not in line:
            line = line[:self.MAX_LINE_LENGTH]

        for parser in self.parsers:
            if not parser.complete:
                parser.parse_line(line, self.lineno)

        self.lineno += 1

    def get_artifact(self):
        """Return the job artifact built from all parsers."""
        for sp in self.parsers:
            self.artifact[sp.name] = sp.get_artifact()
        return self.artifact


class BuildbotJobArtifactBuilder(ArtifactBuilderBase):
    """
    Gather error and details for this job.

    This parser gathers the data that shows on the bottom panel of the main
    TBPL page.

    """

    def __init__(self, url=None):
        """Construct a job artifact builder."""
        super(BuildbotJobArtifactBuilder, self).__init__(url)
        self.parsers = [
            TinderboxPrintParser()
        ]
        self.name = "Job Info"


class BuildbotLogViewArtifactBuilder(ArtifactBuilderBase):
    """Makes the artifact for the structured log viewer."""

    def __init__(self, url=None, check_errors=True):
        """Construct artifact builder for the log viewer"""
        super(BuildbotLogViewArtifactBuilder, self).__init__(url)
        self.parsers = [
            HeaderParser(),
            StepParser(check_errors=check_errors)
        ]
        self.name = "Structured Log"

class BuildbotPerformanceDataArtifactBuilder(ArtifactBuilderBase):
    """Makes the artifact for performance data."""

    def __init__(self, url=None, check_errors=True):
        """Construct artifact builder for the log viewer"""
        super(BuildbotPerformanceDataArtifactBuilder, self).__init__(url)
        self.parsers = [
            TalosParser()
        ]
        self.name = "talos_data"
