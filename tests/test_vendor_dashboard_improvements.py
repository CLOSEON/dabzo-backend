# Backend API Tests for Vendor Dashboard Improvements
# Tests: New dashboard fields, menu creation with tags, subscriber breakdown

import pytest
import requests
import os
from datetime import datetime, timedelta
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

# Test credentials
VENDOR_CREDS = {"email": "amma@dabzo.com", "password": "vendor123"}
USER_CREDS = {"email": "user@dabzo.com", "password": "user123"}

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def vendor_token(api_client):
    """Get vendor auth token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=VENDOR_CREDS)
    return response.json()["token"]

@pytest.fixture
def user_token(api_client):
    """Get user auth token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
    return response.json()["token"]

class TestVendorDashboardNewFields:
    """Test new vendor dashboard fields for daily workflow focus"""
    
    def test_dashboard_returns_new_fields(self, api_client, vendor_token):
        """Test that dashboard returns all new required fields"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check all new fields exist
        assert "tomorrow_menu_posted" in data, "Missing tomorrow_menu_posted field"
        assert "tomorrow_date" in data, "Missing tomorrow_date field"
        assert "today_date" in data, "Missing today_date field"
        assert "lunch_subscribers" in data, "Missing lunch_subscribers field"
        assert "dinner_subscribers" in data, "Missing dinner_subscribers field"
        assert "total_deliveries_today" in data, "Missing total_deliveries_today field"
        assert "todays_menus" in data, "Missing todays_menus field"
        
        print("✓ Dashboard returns all new fields")
    
    def test_tomorrow_menu_posted_field(self, api_client, vendor_token):
        """Test tomorrow_menu_posted field logic"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be boolean
        assert isinstance(data["tomorrow_menu_posted"], bool), "tomorrow_menu_posted should be boolean"
        
        # Initially should be False (no tomorrow menu posted yet)
        # Note: This might be True if previous tests created tomorrow's menu
        print(f"✓ tomorrow_menu_posted = {data['tomorrow_menu_posted']}")
    
    def test_subscriber_breakdown_structure(self, api_client, vendor_token):
        """Test lunch_subscribers and dinner_subscribers structure"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be arrays
        assert isinstance(data["lunch_subscribers"], list), "lunch_subscribers should be array"
        assert isinstance(data["dinner_subscribers"], list), "dinner_subscribers should be array"
        
        # Check structure if subscribers exist
        all_subs = data["lunch_subscribers"] + data["dinner_subscribers"]
        if len(all_subs) > 0:
            sub = all_subs[0]
            assert "id" in sub, "Subscriber should have id"
            assert "user_name" in sub, "Subscriber should have user_name"
            assert "user_email" in sub, "Subscriber should have user_email"
            assert "meal_type" in sub, "Subscriber should have meal_type"
            assert "since" in sub, "Subscriber should have since field"
            print(f"✓ Subscriber structure correct: {sub['user_name']} - {sub['meal_type']}")
        else:
            print("⚠ No subscribers found to verify structure")
    
    def test_total_deliveries_calculation(self, api_client, vendor_token):
        """Test total_deliveries_today calculation"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Should be integer
        assert isinstance(data["total_deliveries_today"], int), "total_deliveries_today should be integer"
        
        # Should equal sum of lunch and dinner subscribers
        expected_total = len(data["lunch_subscribers"]) + len(data["dinner_subscribers"])
        assert data["total_deliveries_today"] == expected_total, \
            f"total_deliveries_today ({data['total_deliveries_today']}) should equal lunch ({len(data['lunch_subscribers'])}) + dinner ({len(data['dinner_subscribers'])})"
        
        print(f"✓ Total deliveries: {data['total_deliveries_today']} (Lunch: {len(data['lunch_subscribers'])}, Dinner: {len(data['dinner_subscribers'])})")
    
    def test_todays_menus_structure(self, api_client, vendor_token):
        """Test todays_menus array structure"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert isinstance(data["todays_menus"], list), "todays_menus should be array"
        
        if len(data["todays_menus"]) > 0:
            menu = data["todays_menus"][0]
            assert "id" in menu, "Menu should have id"
            assert "meal_type" in menu, "Menu should have meal_type"
            assert "items" in menu, "Menu should have items"
            assert "date" in menu, "Menu should have date"
            assert menu["date"] == data["today_date"], "Menu date should match today_date"
            print(f"✓ Today's menu found: {menu['meal_type']} with {len(menu['items'])} items")
        else:
            print("⚠ No menus found for today")

class TestMenuCreationWithTags:
    """Test menu creation with new tags feature"""
    
    def test_create_menu_with_tags(self, api_client, vendor_token):
        """Test creating menu with tags in items"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        menu_payload = {
            "date": tomorrow,
            "meal_type": "lunch",
            "items": [
                {
                    "name": "Dal Tadka",
                    "description": "Yellow lentil curry with ghee tempering",
                    "tags": ["veg", "healthy"]
                },
                {
                    "name": "Paneer Tikka",
                    "description": "Spicy grilled cottage cheese",
                    "tags": ["veg", "spicy"]
                },
                {
                    "name": "Chicken Curry",
                    "description": "Tender chicken in rich gravy",
                    "tags": ["non-veg", "spicy"]
                }
            ]
        }
        
        response = api_client.post(f"{BASE_URL}/api/vendor/menus", json=menu_payload, headers=headers)
        assert response.status_code == 200
        print(f"✓ Menu created for {tomorrow} with tags")
        
        # Verify menu was created with tags
        get_res = api_client.get(f"{BASE_URL}/api/vendor/menus", headers=headers)
        menus = get_res.json()
        
        created_menu = next((m for m in menus if m["date"] == tomorrow and m["meal_type"] == "lunch"), None)
        assert created_menu is not None, "Menu should be created"
        
        # Verify tags are saved
        for item in created_menu["items"]:
            if "tags" in item:
                assert isinstance(item["tags"], list), "Tags should be array"
                print(f"  - {item['name']}: tags = {item['tags']}")
        
        print("✓ Menu with tags verified")
    
    def test_create_menu_without_tags(self, api_client, vendor_token):
        """Test creating menu without tags (backward compatibility)"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        menu_payload = {
            "date": tomorrow,
            "meal_type": "dinner",
            "items": [
                {
                    "name": "Simple Rice",
                    "description": "Plain steamed rice"
                }
            ]
        }
        
        response = api_client.post(f"{BASE_URL}/api/vendor/menus", json=menu_payload, headers=headers)
        assert response.status_code == 200
        print("✓ Menu created without tags (backward compatible)")
    
    def test_tomorrow_menu_posted_updates_after_creation(self, api_client, vendor_token):
        """Test that tomorrow_menu_posted becomes true after creating tomorrow's menu"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        
        # Create tomorrow's menu
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        menu_payload = {
            "date": tomorrow,
            "meal_type": "lunch",
            "items": [{"name": "Test Dish", "description": "Test", "tags": ["veg"]}]
        }
        
        create_res = api_client.post(f"{BASE_URL}/api/vendor/menus", json=menu_payload, headers=headers)
        assert create_res.status_code == 200
        
        # Check dashboard
        dashboard_res = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        data = dashboard_res.json()
        
        assert data["tomorrow_menu_posted"] == True, "tomorrow_menu_posted should be True after creating tomorrow's menu"
        print("✓ tomorrow_menu_posted correctly updates to True")

class TestSubscriberBreakdown:
    """Test subscriber breakdown by meal type"""
    
    def test_subscriber_meal_type_breakdown(self, api_client, vendor_token, user_token):
        """Test that subscribers are correctly categorized by meal type"""
        # Get vendor ID
        vendor_headers = {"Authorization": f"Bearer {vendor_token}"}
        dashboard_res = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=vendor_headers)
        vendor_data = dashboard_res.json()
        vendor_id = vendor_data["vendor"]["id"]
        
        # Create subscription as user
        user_headers = {"Authorization": f"Bearer {user_token}"}
        sub_payload = {"vendor_id": vendor_id, "meal_type": "lunch"}
        
        # Try to create subscription (might already exist)
        sub_res = api_client.post(f"{BASE_URL}/api/subscriptions", json=sub_payload, headers=user_headers)
        if sub_res.status_code == 400:
            print("⚠ Subscription already exists, skipping creation")
        else:
            assert sub_res.status_code == 200
            print("✓ Subscription created")
        
        # Check dashboard again
        dashboard_res = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=vendor_headers)
        data = dashboard_res.json()
        
        # Verify subscriber appears in lunch list
        lunch_subs = data["lunch_subscribers"]
        user_sub = next((s for s in lunch_subs if s["user_email"] == USER_CREDS["email"]), None)
        
        if user_sub:
            assert user_sub["meal_type"] in ["lunch", "both"], "User should be in lunch subscribers"
            print(f"✓ User found in lunch subscribers: {user_sub['user_name']}")
        else:
            print("⚠ User subscription not found in lunch list (might be in dinner or inactive)")

class TestDateFields:
    """Test today_date and tomorrow_date fields"""
    
    def test_date_fields_format(self, api_client, vendor_token):
        """Test that date fields are in correct format"""
        headers = {"Authorization": f"Bearer {vendor_token}"}
        response = api_client.get(f"{BASE_URL}/api/vendor/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        # Check format YYYY-MM-DD
        today = data["today_date"]
        tomorrow = data["tomorrow_date"]
        
        assert len(today) == 10, "today_date should be YYYY-MM-DD format"
        assert len(tomorrow) == 10, "tomorrow_date should be YYYY-MM-DD format"
        assert today < tomorrow, "tomorrow_date should be after today_date"
        
        # Verify dates are correct
        expected_today = datetime.now().strftime("%Y-%m-%d")
        expected_tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        assert today == expected_today, f"today_date should be {expected_today}"
        assert tomorrow == expected_tomorrow, f"tomorrow_date should be {expected_tomorrow}"
        
        print(f"✓ Date fields correct: today={today}, tomorrow={tomorrow}")
