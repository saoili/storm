#
# Copyright (c) 2006, 2007 Canonical
#
# Written by Gustavo Niemeyer <gustavo@niemeyer.net>
#
# This file is part of Storm Object Relational Mapper.
#
# Storm is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as
# published by the Free Software Foundation; either version 2.1 of
# the License, or (at your option) any later version.
#
# Storm is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
import thread, weakref, gc

from tests.helper import TestHelper

try:
    import transaction
except ImportError:
    has_transaction = False
else:
    has_transaction = True
    from storm.zope.interfaces import IZStorm, ZStormError
    from storm.zope.zstorm import ZStorm, StoreDataManager

try:
    from zope.component import provideUtility, getUtility
except ImportError:
    has_zope_component = False
else:
    has_zope_component = True

has_zope = has_transaction and has_zope_component


from storm.exceptions import OperationalError
from storm.locals import Store, Int


class ZStormTest(TestHelper):

    def is_supported(self):
        return has_transaction

    def setUp(self):
        self.zstorm = ZStorm()

    def tearDown(self):
        # Reset the utility to cleanup the StoreSynchronizer's from the
        # transaction.
        self.zstorm._reset()
        # Free the transaction to avoid having errors that cross
        # test cases.
        transaction.manager.free(transaction.get())

    def test_create(self):
        store = self.zstorm.create(None, "sqlite:")
        self.assertTrue(isinstance(store, Store))

    def test_create_twice_unnamed(self):
        store = self.zstorm.create(None, "sqlite:")
        store.execute("CREATE TABLE test (id INTEGER)")
        store.commit()

        store = self.zstorm.create(None, "sqlite:")
        self.assertRaises(OperationalError,
                          store.execute, "SELECT * FROM test")

    def test_create_twice_same_name(self):
        store = self.zstorm.create("name", "sqlite:")
        self.assertRaises(ZStormError, self.zstorm.create, "name", "sqlite:")

    def test_create_and_get_named(self):
        store = self.zstorm.create("name", "sqlite:")
        self.assertTrue(self.zstorm.get("name") is store)

    def test_create_and_get_named_another_thread(self):
        store = self.zstorm.create("name", "sqlite:")

        raised = []

        lock = thread.allocate_lock()
        lock.acquire()
        def f():
            try:
                try:
                    self.zstorm.get("name")
                except ZStormError:
                    raised.append(True)
            finally:
                lock.release()
        thread.start_new_thread(f, ())
        lock.acquire()

        self.assertTrue(raised)

    def test_get_unexistent(self):
        self.assertRaises(ZStormError, self.zstorm.get, "name")

    def test_get_with_uri(self):
        store = self.zstorm.get("name", "sqlite:")
        self.assertTrue(isinstance(store, Store))
        self.assertTrue(self.zstorm.get("name") is store)
        self.assertTrue(self.zstorm.get("name", "sqlite:") is store)

    def test_set_default_uri(self):
        self.zstorm.set_default_uri("name", "sqlite:")
        store = self.zstorm.get("name")
        self.assertTrue(isinstance(store, Store))

    def test_create_default(self):
        self.zstorm.set_default_uri("name", "sqlite:")
        store = self.zstorm.create("name")
        self.assertTrue(isinstance(store, Store))

    def test_create_default_twice(self):
        self.zstorm.set_default_uri("name", "sqlite:")
        self.zstorm.create("name")
        self.assertRaises(ZStormError, self.zstorm.create, "name")

    def test_iterstores(self):
        store1 = self.zstorm.create(None, "sqlite:")
        store2 = self.zstorm.create(None, "sqlite:")
        store3 = self.zstorm.create("name", "sqlite:")
        stores = []
        for name, store in self.zstorm.iterstores():
            stores.append((name, store))
        self.assertEquals(len(stores), 3)
        self.assertEquals(set(stores),
                          set([(None, store1), (None, store2),
                               ("name", store3)]))

    def test_get_name(self):
        store = self.zstorm.create("name", "sqlite:")
        self.assertEquals(self.zstorm.get_name(store), "name")

    def test_get_name_with_removed_store(self):
        store = self.zstorm.create("name", "sqlite:")
        self.assertEquals(self.zstorm.get_name(store), "name")
        self.zstorm.remove(store)
        self.assertEquals(self.zstorm.get_name(store), None)

    def test_default_databases(self):
        self.zstorm.set_default_uri("name1", "sqlite:1")
        self.zstorm.set_default_uri("name2", "sqlite:2")
        self.zstorm.set_default_uri("name3", "sqlite:3")
        default_uris = self.zstorm.get_default_uris()
        self.assertEquals(default_uris, {"name1": "sqlite:1",
                                         "name2": "sqlite:2",
                                         "name3": "sqlite:3"})

    def _get_joined_stores(self):
        """Returns the stores that are joined to the current transaction."""
        return set(dm._store for dm in transaction.get()._resources
                   if isinstance(dm, StoreDataManager))

    def assertInTransaction(self, store):
        """Check that the given store is joined to the transaction."""
        self.assertTrue(store in self._get_joined_stores(),
                        "%r should be joined to the transaction")

    def assertNotInTransaction(self, store):
        """Check that the given store is not joined to the transaction."""
        self.assertTrue(store not in self._get_joined_stores(),
                        "%r should not be joined to the transaction")

    def test_wb_store_joins_transaction_on_use(self):
        store = self.zstorm.get("name", "sqlite:")
        self.assertNotInTransaction(store)
        store.execute("SELECT 1")
        self.assertInTransaction(store)

    def test_wb_store_joins_transaction_on_use_after_commit(self):
        store = self.zstorm.get("name", "sqlite:")
        store.execute("SELECT 1")
        transaction.commit()
        self.assertNotInTransaction(store)
        store.execute("SELECT 1")
        self.assertInTransaction(store)

    def test_wb_store_joins_transaction_on_use_after_abort(self):
        store = self.zstorm.get("name", "sqlite:")
        store.execute("SELECT 1")
        transaction.abort()
        self.assertNotInTransaction(store)
        store.execute("SELECT 1")
        self.assertInTransaction(store)

    def test_remove(self):
        removed_store = self.zstorm.get("name", "sqlite:")
        self.zstorm.remove(removed_store)
        for name, store in self.zstorm.iterstores():
            self.assertNotEquals(store, removed_store)
        self.assertRaises(ZStormError, self.zstorm.get, "name")

    def test_wb_removed_store_does_not_join_transaction(self):
        """If a store has been removed, it will not join the transaction."""
        store = self.zstorm.get("name", "sqlite:")
        self.zstorm.remove(store)
        store.execute("SELECT 1")
        self.assertNotInTransaction(store)

    def test_wb_removed_store_does_not_join_future_transactions(self):
        """If a store has been removed after joining a transaction, it
        will not join new transactions."""
        store = self.zstorm.get("name", "sqlite:")
        store.execute("SELECT 1")
        self.zstorm.remove(store)
        self.assertInTransaction(store)

        transaction.abort()
        store.execute("SELECT 1")
        self.assertNotInTransaction(store)

    def test_wb_reset(self):
        """_reset is used to reset the zstorm utility between zope test runs.
        """
        store = self.zstorm.get("name", "sqlite:")
        self.zstorm._reset()
        self.assertEqual(list(self.zstorm.iterstores()), [])

    def test_store_strong_reference(self):
        """
        The zstorm utility should be a strong reference to named stores so that
        it doesn't recreate stores uselessly.
        """
        store = self.zstorm.get("name", "sqlite:")
        store_ref = weakref.ref(store)
        transaction.abort()
        del store
        gc.collect()
        self.assertNotIdentical(store_ref(), None)
        store = self.zstorm.get("name")
        self.assertIdentical(store_ref(), store)


class ZStormUtilityTest(TestHelper):

    def is_supported(self):
        return has_zope_component

    def test_utility(self):
        provideUtility(ZStorm())
        self.assertTrue(isinstance(getUtility(IZStorm), ZStorm))

