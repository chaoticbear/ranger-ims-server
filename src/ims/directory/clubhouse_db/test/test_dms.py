##
# See the file COPYRIGHT for copyright information.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
##

"""
Tests for L{ims.directory.clubhouse_db._dms}.
"""

from collections.abc import MutableSequence
from typing import Any, cast

from twisted.internet.defer import Deferred, fail, succeed

from ims.ext.trial import TestCase
from ims.store._db import Rows

from ..._directory import hashPassword
from .._dms import DutyManagementSystem, fullName


__all__ = ()


class DutyManagementSystemTests(TestCase):
    """
    Tests for L{DutyManagementSystem}.
    """

    def setUp(self) -> None:
        """
        Patch adbapi module.
        """
        self.dummyADBAPI = DummyADBAPI()

        import ims.directory.clubhouse_db._dms

        self.patch(ims.directory.clubhouse_db._dms, "adbapi", self.dummyADBAPI)

    def dms(self) -> DutyManagementSystem:
        """
        Gimme a DMS.
        """
        self.host = "the-server"
        self.database = "the-db"
        self.username = "the-user"
        self.password = "the-password"  # nosec: B105

        return DutyManagementSystem(
            host=self.host,
            database=self.database,
            username=self.username,
            password=self.password,
            cacheInterval=5,
        )

    def test_init(self) -> None:
        """
        Initialized state is as expected.
        """
        dms = self.dms()

        self.assertEqual(dms.host, self.host)
        self.assertEqual(dms.database, self.database)
        self.assertEqual(dms.username, self.username)
        self.assertEqual(dms.password, self.password)

    def test_dbpool(self) -> None:
        """
        L{DutyManagementSystem.dbpool} returns a DB pool.
        """
        dms = self.dms()
        dbpool = cast(DummyConnectionPool, dms.dbpool)

        self.assertIsInstance(dbpool, DummyConnectionPool)

        self.assertEqual(dbpool.dbapiname, "pymysql")
        self.assertEqual(dbpool.connkw["host"], self.host)
        self.assertEqual(dbpool.connkw["database"], self.database)
        self.assertEqual(dbpool.connkw["user"], self.username)
        self.assertEqual(dbpool.connkw["password"], self.password)

    def test_personnel(self) -> None:
        """
        L{DutyManagementSystem.personnel} returns L{Ranger} objects.
        """
        dms = self.dms()

        personnel = self.successResultOf(dms.personnel())

        self.assertEqual(
            [p.handle for p in personnel],
            [p[1] for p in cannedPersonnel],
        )


class UtilTests(TestCase):
    """
    Tests for L{ims.directory.clubhouse_db}.
    """

    def test_fullName(self) -> None:
        """
        L{fullName} combines first/middle/last correctly.
        """
        self.assertEqual(fullName("Bob", "", "Smith"), "Bob Smith")
        self.assertEqual(fullName("Bob", "Q", "Smith"), "Bob Q. Smith")


class DummyQuery:
    """
    Represents a call to C{runQuery}.
    """

    def __init__(self, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        self.args = args
        self.kwargs = kwargs

    def sql(self) -> str:
        """
        Produce normalized SQL for the query.
        """
        sql = cast(str, self.args[0])

        # Collapse spaces
        sql = " ".join(sql.split())

        return sql


class DummyConnectionPool:
    """
    Mock for L{adbapi.ConnectionPool}.
    """

    def __init__(self, dbapiname: str, **connkw: dict[str, Any]) -> None:
        self.dbapiname = dbapiname
        self.connkw = connkw
        self.queries: MutableSequence[DummyQuery] = []

    def runQuery(
        self, *args: tuple[Any, ...], **kw: dict[str, Any]
    ) -> Deferred[Rows]:
        query = DummyQuery(args, kw)

        self.queries.append(query)

        sql = query.sql()

        def fixPassword(
            person: tuple[int, str, str, str, str, str, str, bool, str]
        ) -> tuple[int, str, str, str, str, str, str, bool, str]:
            return (
                person[0],
                person[1],
                person[2],
                person[3],
                person[4],
                person[5],
                person[6],
                person[7],
                hashPassword(person[8]),
            )

        if sql == (
            "select "
            "id, callsign, first_name, mi, last_name, "
            "email, status, on_site, password "
            "from person where status in "
            "('active', 'inactive', 'vintage', 'auditor')"
        ):
            rows = (fixPassword(p) for p in cannedPersonnel)
            return succeed(rows)  # type: ignore[arg-type]

        if sql == ("select id, title from position where all_rangers = 0"):
            return succeed(())  # type: ignore[arg-type]

        if sql == ("select person_id, position_id from person_position"):
            return succeed(())  # type: ignore[arg-type]

        return fail(AssertionError(f"No canned response for query: {sql}"))


class DummyADBAPI:
    """
    Mock for L{adbapi}.
    """

    def __init__(self) -> None:
        self.ConnectionPool = DummyConnectionPool


cannedPersonnel = (
    (
        1,
        "Easy E",
        "Eric",
        "P",
        "Grant",
        "easye@example.com",
        "active",
        True,
        "easypass",
    ),
    (
        2,
        "Weso",
        "Wes",
        "",
        "Johnson",
        "weso@example.com",
        "active",
        True,
        "wespass",
    ),
    (
        3,
        "SciFi",
        "Fred",
        "",
        "McCord",
        "scifi@example.com",
        "active",
        True,
        "scipass",
    ),
    (
        4,
        "Slumber",
        "Sleepy",
        "T",
        "Dwarf",
        "slumber@example.com",
        "inactive",
        False,
        "sleepypass",
    ),
    (
        5,
        "Tool",
        "Wilfredo",
        "",
        "Sanchez",
        "tool@example.com",
        "vintage",
        True,
        "toolpass",
    ),
    (
        6,
        "Tulsa",
        "Curtis",
        "",
        "Kline",
        "tulsa@example.com",
        "vintage",
        True,
        "tulsapass",
    ),
)
