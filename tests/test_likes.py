"""Full favorite IDs and confirmed add/remove without touching a real account."""
from types import SimpleNamespace as NS
import unittest

from test_recommendations import load_service


class LikesTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []
        self.accepted = True
        def add(ident, user_id):
            self.calls.append(("add",ident,user_id))
            return self.accepted
        def remove(ident, user_id):
            self.calls.append(("remove",ident,user_id))
            return self.accepted
        def fetch(user_id):
            return NS(tracks_ids=[str(i) for i in range(1,750)]+["749:8","750:8","invalid"])
        client=NS(users_likes_tracks_add=add, users_likes_tracks_remove=remove, users_likes_tracks=fetch)
        async def executor(fn): return fn()
        self.service=load_service()(NS(async_add_executor_job=executor),"station")
        async def get_client(): return client
        async def account(): return {"uid":"account-1"}
        self.service.client, self.service.account = get_client, account

    async def test_add_remove_use_connected_account_and_require_confirmation(self):
        await self.service.set_like("123",True)
        await self.service.set_like("123:9",False)
        self.assertEqual(self.calls,[("add","123","account-1"),("remove","123:9","account-1")])
        self.accepted=False
        with self.assertRaisesRegex(RuntimeError,"не подтвердила"):
            await self.service.set_like("123",True)

    async def test_invalid_ids_do_not_reach_account_api(self):
        for value in ["", "media_player.shield", "https://example.test/123", "-1", "123:bad"]:
            with self.subTest(value=value),self.assertRaises(RuntimeError):
                await self.service.set_like(value,True)
        self.assertEqual(self.calls,[])

    async def test_full_ids_are_not_limited_to_first_500_tracks(self):
        ids=await self.service.liked_track_ids()
        self.assertEqual(len(ids),750)
        self.assertIn("750",ids)
        self.assertNotIn("invalid",ids)
        self.assertEqual(ids.count("749"),1)


if __name__ == "__main__":
    unittest.main()
