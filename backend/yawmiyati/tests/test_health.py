from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse


class HealthViewTests(TestCase):
    def test_healthy_returns_200(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["db"])
        self.assertEqual(data["migrations"], "ok")

    def test_pending_migrations_returns_503(self):
        fake_plan = [("fake_app", MagicMock())]
        with patch("yawmiyati.health_urls.MigrationExecutor") as MockExecutor:
            instance = MockExecutor.return_value
            instance.migration_plan.return_value = fake_plan
            instance.loader.graph.leaf_nodes.return_value = []
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertTrue(data["db"])
        self.assertEqual(data["migrations"], "pending")

    def test_db_down_returns_503(self):
        with patch(
            "yawmiyati.health_urls.connection"
        ) as mock_conn:
            mock_conn.cursor.side_effect = Exception("connection refused")
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertFalse(data["db"])

    def test_migration_check_error_returns_503(self):
        with patch("yawmiyati.health_urls.MigrationExecutor", side_effect=Exception("boom")):
            response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 503)
        data = response.json()
        self.assertEqual(data["status"], "degraded")
        self.assertTrue(data["db"])
        self.assertEqual(data["migrations"], "unknown")

    def test_body_shape_is_identical_for_200_and_503(self):
        ok = self.client.get(reverse("health"))
        with patch("yawmiyati.health_urls.connection") as mock_conn:
            mock_conn.cursor.side_effect = Exception("connection refused")
            down = self.client.get(reverse("health"))
        self.assertEqual((ok.status_code, down.status_code), (200, 503))
        self.assertEqual(set(ok.json()), {"status", "db", "migrations"})
        self.assertEqual(set(down.json()), set(ok.json()))
        self.assertEqual(down["Content-Type"], ok["Content-Type"])
