# Backend API Tests for Dabzo Food Platform
# Tests: Auth, Vendors, Subscriptions, Admin, Vendor Dashboard

import pytest
import requests
import os
from datetime import datetime
from pathlib import Path

# Read backend URL from frontend .env file
def get_backend_url():
    env_path = Path('/app/frontend/.env')
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                if line.startswith('EXPO_PUBLIC_BACKEND_URL='):
                    return line.split('=', 1)[1].strip()
    return ''

BASE_URL = get_backend_url()

# Test credentials from seed data
USER_CREDS = {"email": "user@dabzo.com", "password": "user123"}
ADMIN_CREDS = {"email": "admin@dabzo.com", "password": "admin123"}
VENDOR_CREDS = {"email": "amma@dabzo.com", "password": "vendor123"}

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

class TestHealth:
    """Health check endpoint"""
    
    def test_health_check(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "dabzo-api"
        print("✓ Health check passed")

class TestAuth:
    """Authentication endpoints"""
    
    def test_user_login_success(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "user" in data
        assert data["user"]["email"] == USER_CREDS["email"]
        assert data["user"]["role"] == "user"
        print("✓ User login successful")
    
    def test_admin_login_success(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "admin"
        print("✓ Admin login successful")
    
    def test_vendor_login_success(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json=VENDOR_CREDS)
        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert data["user"]["role"] == "vendor"
        print("✓ Vendor login successful")
    
    def test_login_invalid_credentials(self, api_client):
        response = api_client.post(f"{BASE_URL}/api/auth/login", json={
            "email": "wrong@test.com", "password": "wrongpass"
        })
        assert response.status_code == 401
        print("✓ Invalid login rejected correctly")
    
    def test_get_me_with_token(self, api_client):
        # Login first
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        token = login_res.json()["token"]
        
        # Get user info
        response = api_client.get(f"{BASE_URL}/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == USER_CREDS["email"]
        assert "password_hash" not in data  # Should be excluded
        print("✓ Get me endpoint working")

class TestVendors:
    """Public vendor endpoints"""
    
    def test_list_vendors(self, api_client):
        response = api_client.get(f"{BASE_URL}/api/vendors")
        assert response.status_code == 200
        vendors = response.json()
        assert isinstance(vendors, list)
        assert len(vendors) >= 3  # Seeded vendors
        
        # Check vendor structure
        vendor = vendors[0]
        assert "id" in vendor
        assert "business_name" in vendor
        assert "cuisine_type" in vendor
        assert "price_per_meal" in vendor
        assert "reliability_score" in vendor
        assert "is_approved" in vendor
        assert vendor["is_approved"] == True  # Only approved vendors shown
        assert "_id" not in vendor  # MongoDB _id should be excluded
        print(f"✓ Listed {len(vendors)} vendors")
    
    def test_get_vendor_detail(self, api_client):
        # Get vendor list first
        vendors = api_client.get(f"{BASE_URL}/api/vendors").json()
        vendor_id = vendors[0]["id"]
        
        # Get vendor detail
        response = api_client.get(f"{BASE_URL}/api/vendors/{vendor_id}")
        assert response.status_code == 200
        vendor = response.json()
        assert vendor["id"] == vendor_id
        assert "business_name" in vendor
        assert "delivery_areas" in vendor
        print("✓ Vendor detail retrieved")
    
    def test_get_vendor_menus(self, api_client):
        # Get vendor list first
        vendors = api_client.get(f"{BASE_URL}/api/vendors").json()
        vendor_id = vendors[0]["id"]
        
        # Get vendor menus
        today = datetime.now().strftime("%Y-%m-%d")
        response = api_client.get(f"{BASE_URL}/api/vendors/{vendor_id}/menus?date={today}")
        assert response.status_code == 200
        menus = response.json()
        assert isinstance(menus, list)
        # Should have at least 1 menu from seed data
        if len(menus) > 0:
            menu = menus[0]
            assert "meal_type" in menu
            assert "items" in menu
            assert "date" in menu
            print(f"✓ Retrieved {len(menus)} menus for today")
        else:
            print("⚠ No menus found for today")

class TestSubscriptions:
    """Subscription CRUD operations"""
    
    def test_create_subscription_and_verify(self, api_client):
        # Login as user
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get a vendor
        vendors = api_client.get(f"{BASE_URL}/api/vendors").json()
        vendor_id = vendors[0]["id"]
        
        # Create subscription
        sub_payload = {"vendor_id": vendor_id, "meal_type": "lunch"}
        create_res = api_client.post(f"{BASE_URL}/api/subscriptions", json=sub_payload, headers=headers)
        assert create_res.status_code == 200
        
        # Verify subscription was created by fetching list
        get_res = api_client.get(f"{BASE_URL}/api/subscriptions", headers=headers)
        assert get_res.status_code == 200
        subs = get_res.json()
        assert len(subs) > 0
        
        # Find the subscription we just created
        created_sub = next((s for s in subs if s["vendor_id"] == vendor_id), None)
        assert created_sub is not None
        assert created_sub["status"] == "active"
        assert created_sub["meal_type"] == "lunch"
        print("✓ Subscription created and verified")
    
    def test_get_subscriptions(self, api_client):
        # Login as user
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/subscriptions", headers=headers)
        assert response.status_code == 200
        subs = response.json()
        assert isinstance(subs, list)
        print(f"✓ Retrieved {len(subs)} subscriptions")
    
    def test_subscription_requires_auth(self, api_client):
        vendors = api_client.get(f"{BASE_URL}/api/vendors").json()
        vendor_id = vendors[0]["id"]
        
        response = api_client.post(f"{BASE_URL}/api/subscriptions", json={
            "vendor_id": vendor_id, "meal_type": "lunch"
        })
        assert response.status_code == 401
        print("✓ Subscription requires authentication")

class TestAdminEndpoints:
    """Admin dashboard and vendor management"""
    
    def test_admin_dashboard(self, api_client):
        # Login as admin
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/admin/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_users" in data
        assert "total_vendors" in data
        assert "approved_vendors" in data
        assert "pending_vendors" in data
        assert "active_subscriptions" in data
        assert "open_complaints" in data
        print("✓ Admin dashboard data retrieved")
    
    def test_admin_list_vendors(self, api_client):
        # Login as admin
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        assert response.status_code == 200
        vendors = response.json()
        assert isinstance(vendors, list)
        assert len(vendors) >= 3
        print(f"✓ Admin listed {len(vendors)} vendors")
    
    def test_admin_approve_vendor(self, api_client):
        # Login as admin
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Get vendors
        vendors = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers).json()
        vendor_id = vendors[0]["id"]
        
        # Approve vendor
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/approve", headers=headers)
        assert response.status_code == 200
        print("✓ Admin approved vendor")
    
    def test_admin_endpoints_require_admin_role(self, api_client):
        # Login as regular user
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/admin/dashboard", headers=headers)
        assert response.status_code == 403
        print("✓ Admin endpoints require admin role")

class TestVendorEndpoints:
    """Vendor dashboard and menu management"""
    
    def test_vendor_dashboard(self, api_client):
        # Login as vendor
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=VENDOR_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "vendor" in data
        assert "active_subscribers" in data
        assert "total_subscribers" in data
        assert "open_complaints" in data
        assert "todays_menus" in data
        print("✓ Vendor dashboard data retrieved")
    
    def test_vendor_get_menus(self, api_client):
        # Login as vendor
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=VENDOR_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/vendor/menus", headers=headers)
        assert response.status_code == 200
        menus = response.json()
        assert isinstance(menus, list)
        print(f"✓ Vendor retrieved {len(menus)} menus")
    
    def test_vendor_create_menu(self, api_client):
        # Login as vendor
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=VENDOR_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create menu for tomorrow
        tomorrow = datetime.now().strftime("%Y-%m-%d")
        menu_payload = {
            "date": tomorrow,
            "meal_type": "dinner",
            "items": [
                {"name": "Test Dish", "description": "Test description"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/vendor/menus", json=menu_payload, headers=headers)
        assert response.status_code == 200
        
        # Verify menu was created
        get_res = api_client.get(f"{BASE_URL}/api/vendor/menus", headers=headers)
        menus = get_res.json()
        created_menu = next((m for m in menus if m["meal_type"] == "dinner" and m["date"] == tomorrow), None)
        assert created_menu is not None
        print("✓ Vendor created menu successfully")
    
    def test_vendor_endpoints_require_vendor_role(self, api_client):
        # Login as regular user
        login_res = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
        token = login_res.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        assert response.status_code == 403
        print("✓ Vendor endpoints require vendor role")
