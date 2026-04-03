# Backend API Tests for Admin Quality Enforcement Features
# Tests: Admin dashboard system health, low reliability vendors, vendor actions (warn, reduce-visibility, disable)

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

# Test credentials
ADMIN_CREDS = {"email": "admin@dabzo.com", "password": "admin123"}
USER_CREDS = {"email": "user@dabzo.com", "password": "user123"}
VENDOR_CREDS = {"email": "amma@dabzo.com", "password": "vendor123"}

@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session

@pytest.fixture
def admin_token(api_client):
    """Get admin auth token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=ADMIN_CREDS)
    return response.json()["token"]

@pytest.fixture
def user_token(api_client):
    """Get user auth token"""
    response = api_client.post(f"{BASE_URL}/api/auth/login", json=USER_CREDS)
    return response.json()["token"]

class TestAdminDashboardSystemHealth:
    """Test admin dashboard system health score and low reliability vendors"""
    
    def test_admin_dashboard_returns_system_health_score(self, api_client, admin_token):
        """Test that admin dashboard returns system_health_score field"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = api_client.get(f"{BASE_URL}/api/admin/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "system_health_score" in data, "Missing system_health_score field"
        assert isinstance(data["system_health_score"], int), "system_health_score should be integer"
        assert 0 <= data["system_health_score"] <= 100, "system_health_score should be 0-100"
        
        print(f"✓ System health score: {data['system_health_score']}/100")
    
    def test_admin_dashboard_returns_low_reliability_vendors(self, api_client, admin_token):
        """Test that admin dashboard returns low_reliability_vendors array"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = api_client.get(f"{BASE_URL}/api/admin/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "low_reliability_vendors" in data, "Missing low_reliability_vendors field"
        assert isinstance(data["low_reliability_vendors"], list), "low_reliability_vendors should be array"
        
        print(f"✓ Low reliability vendors: {len(data['low_reliability_vendors'])} vendors")
        
        # Check structure if any low reliability vendors exist
        if len(data["low_reliability_vendors"]) > 0:
            vendor = data["low_reliability_vendors"][0]
            assert "id" in vendor, "Vendor should have id"
            assert "business_name" in vendor, "Vendor should have business_name"
            assert "reliability_score" in vendor, "Vendor should have reliability_score"
            assert "complaint_count" in vendor, "Vendor should have complaint_count"
            assert "open_complaint_count" in vendor, "Vendor should have open_complaint_count"
            assert "score_trend" in vendor, "Vendor should have score_trend"
            assert vendor["reliability_score"] < 4.0, "Low reliability vendor should have score < 4.0"
            print(f"  - {vendor['business_name']}: {vendor['reliability_score']}/5.0, trend: {vendor['score_trend']}")
    
    def test_admin_dashboard_returns_disabled_vendors_count(self, api_client, admin_token):
        """Test that admin dashboard returns disabled_vendors count"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = api_client.get(f"{BASE_URL}/api/admin/dashboard", headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "disabled_vendors" in data, "Missing disabled_vendors field"
        assert isinstance(data["disabled_vendors"], int), "disabled_vendors should be integer"
        assert data["disabled_vendors"] >= 0, "disabled_vendors should be non-negative"
        
        print(f"✓ Disabled vendors count: {data['disabled_vendors']}")

class TestAdminVendorsEnrichedData:
    """Test admin vendors endpoint returns enriched data with complaint counts and trends"""
    
    def test_admin_vendors_returns_complaint_counts(self, api_client, admin_token):
        """Test that admin vendors endpoint returns complaint_count and open_complaint_count"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        
        assert response.status_code == 200
        vendors = response.json()
        
        assert isinstance(vendors, list), "Should return array of vendors"
        assert len(vendors) > 0, "Should have at least one vendor"
        
        vendor = vendors[0]
        assert "complaint_count" in vendor, "Vendor should have complaint_count"
        assert "open_complaint_count" in vendor, "Vendor should have open_complaint_count"
        assert isinstance(vendor["complaint_count"], int), "complaint_count should be integer"
        assert isinstance(vendor["open_complaint_count"], int), "open_complaint_count should be integer"
        
        print(f"✓ Vendor {vendor['business_name']}: {vendor['complaint_count']} complaints ({vendor['open_complaint_count']} open)")
    
    def test_admin_vendors_returns_score_trend(self, api_client, admin_token):
        """Test that admin vendors endpoint returns score_trend field"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        response = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        
        assert response.status_code == 200
        vendors = response.json()
        
        vendor = vendors[0]
        assert "score_trend" in vendor, "Vendor should have score_trend"
        assert vendor["score_trend"] in ["up", "down", "stable"], "score_trend should be up/down/stable"
        
        print(f"✓ Vendor {vendor['business_name']}: trend = {vendor['score_trend']}")

class TestAdminWarnVendor:
    """Test admin warn vendor action"""
    
    def test_warn_vendor_increments_warnings_count(self, api_client, admin_token):
        """Test that warning a vendor increments warnings_count"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[0]["id"]
        initial_warnings = vendors[0].get("warnings_count", 0)
        
        # Warn vendor
        warn_payload = {"reason": "Low reliability score - test warning"}
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/warn", 
                                  json=warn_payload, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "warnings_count" in data
        assert data["warnings_count"] == initial_warnings + 1
        
        print(f"✓ Vendor warned successfully. Warnings count: {data['warnings_count']}")
        
        # Verify by fetching vendor again
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor = next((v for v in vendors if v["id"] == vendor_id), None)
        assert vendor is not None
        assert vendor.get("warnings_count", 0) == data["warnings_count"]
        print(f"✓ Warning count verified in vendor data")
    
    def test_warn_vendor_requires_reason(self, api_client, admin_token):
        """Test that warning requires reason in request body"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[0]["id"]
        
        # Try to warn without reason (should fail validation)
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/warn", 
                                  json={}, headers=headers)
        
        # Should return 422 (validation error) or 400
        assert response.status_code in [400, 422]
        print("✓ Warning without reason rejected correctly")

class TestAdminReduceVisibility:
    """Test admin reduce/restore visibility actions"""
    
    def test_reduce_visibility_sets_flag(self, api_client, admin_token):
        """Test that reduce-visibility sets visibility_reduced=true"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[1]["id"]  # Use second vendor to avoid conflicts
        
        # Reduce visibility
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/reduce-visibility", 
                                  headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        
        print(f"✓ Vendor visibility reduced")
        
        # Verify by fetching vendor again
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor = next((v for v in vendors if v["id"] == vendor_id), None)
        assert vendor is not None
        assert vendor.get("visibility_reduced") == True
        print(f"✓ visibility_reduced flag verified")
    
    def test_restore_visibility_clears_flag(self, api_client, admin_token):
        """Test that restore-visibility sets visibility_reduced=false"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor (use same one we reduced visibility for)
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[1]["id"]
        
        # Restore visibility
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/restore-visibility", 
                                  headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        
        print(f"✓ Vendor visibility restored")
        
        # Verify by fetching vendor again
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor = next((v for v in vendors if v["id"] == vendor_id), None)
        assert vendor is not None
        assert vendor.get("visibility_reduced") == False
        print(f"✓ visibility_reduced flag cleared")

class TestAdminDisableVendor:
    """Test admin disable/enable vendor actions"""
    
    def test_disable_vendor_sets_flags(self, api_client, admin_token):
        """Test that disable sets is_disabled=true and is_approved=false"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[2]["id"]  # Use third vendor
        
        # Disable vendor
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/disable", 
                                  headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        
        print(f"✓ Vendor disabled")
        
        # Verify by fetching vendor again
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor = next((v for v in vendors if v["id"] == vendor_id), None)
        assert vendor is not None
        assert vendor.get("is_disabled") == True
        assert vendor.get("is_approved") == False
        print(f"✓ is_disabled=true and is_approved=false verified")
    
    def test_enable_vendor_clears_flags(self, api_client, admin_token):
        """Test that enable sets is_disabled=false and is_approved=true"""
        headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get the disabled vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor_id = vendors[2]["id"]
        
        # Enable vendor
        response = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/enable", 
                                  headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        
        print(f"✓ Vendor enabled")
        
        # Verify by fetching vendor again
        vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=headers)
        vendors = vendors_res.json()
        vendor = next((v for v in vendors if v["id"] == vendor_id), None)
        assert vendor is not None
        assert vendor.get("is_disabled") == False
        assert vendor.get("is_approved") == True
        print(f"✓ is_disabled=false and is_approved=true verified")

class TestPublicVendorsExcludesDisabled:
    """Test that public /api/vendors endpoint excludes disabled vendors"""
    
    def test_public_vendors_excludes_disabled(self, api_client, admin_token):
        """Test that disabled vendors are hidden from public listing"""
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get all vendors as admin
        admin_vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers)
        all_vendors = admin_vendors_res.json()
        
        # Disable one vendor
        vendor_to_disable = all_vendors[0]
        vendor_id = vendor_to_disable["id"]
        
        disable_res = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/disable", 
                                     headers=admin_headers)
        assert disable_res.status_code == 200
        print(f"✓ Disabled vendor: {vendor_to_disable['business_name']}")
        
        # Get public vendors list (no auth)
        public_vendors_res = api_client.get(f"{BASE_URL}/api/vendors")
        assert public_vendors_res.status_code == 200
        public_vendors = public_vendors_res.json()
        
        # Verify disabled vendor is not in public list
        disabled_vendor_in_public = next((v for v in public_vendors if v["id"] == vendor_id), None)
        assert disabled_vendor_in_public is None, "Disabled vendor should not appear in public listing"
        
        print(f"✓ Disabled vendor hidden from public listing")
        print(f"  Admin sees: {len(all_vendors)} vendors")
        print(f"  Public sees: {len(public_vendors)} vendors")
        
        # Re-enable vendor for cleanup
        enable_res = api_client.put(f"{BASE_URL}/api/admin/vendors/{vendor_id}/enable", 
                                    headers=admin_headers)
        assert enable_res.status_code == 200
        print(f"✓ Vendor re-enabled for cleanup")

class TestComplaintImpactOnReliability:
    """Test that complaints reduce reliability score"""
    
    def test_complaint_reduces_reliability_score(self, api_client, user_token, admin_token):
        """Test that filing a complaint reduces vendor reliability score"""
        user_headers = {"Authorization": f"Bearer {user_token}"}
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Get a vendor
        vendors_res = api_client.get(f"{BASE_URL}/api/vendors")
        vendors = vendors_res.json()
        vendor = vendors[0]
        vendor_id = vendor["id"]
        
        # Get initial reliability score
        admin_vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers)
        admin_vendors = admin_vendors_res.json()
        vendor_data = next((v for v in admin_vendors if v["id"] == vendor_id), None)
        initial_score = vendor_data["reliability_score"]
        
        print(f"Initial reliability score: {initial_score}")
        
        # File a complaint
        complaint_payload = {
            "vendor_id": vendor_id,
            "subject": "Test complaint for reliability impact",
            "description": "Testing that complaints reduce reliability score"
        }
        complaint_res = api_client.post(f"{BASE_URL}/api/complaints", 
                                       json=complaint_payload, headers=user_headers)
        assert complaint_res.status_code == 200
        print("✓ Complaint filed")
        
        # Get updated reliability score
        admin_vendors_res = api_client.get(f"{BASE_URL}/api/admin/vendors", headers=admin_headers)
        admin_vendors = admin_vendors_res.json()
        vendor_data = next((v for v in admin_vendors if v["id"] == vendor_id), None)
        new_score = vendor_data["reliability_score"]
        
        print(f"New reliability score: {new_score}")
        
        # Verify score decreased
        assert new_score < initial_score, "Reliability score should decrease after complaint"
        print(f"✓ Reliability score decreased by {initial_score - new_score}")
