"""Domain verification for security."""
import re
from typing import Optional
import httpx
from src.core.settings import get_settings


class DomainVerifier:
    """Verify domain ownership before crawling."""
    
    def __init__(self):
        self.settings = get_settings()
        self.http_client = httpx.AsyncClient(timeout=10.0)
    
    async def verify(self, domain: str, method: str = "auto",
                     email: str = None, token: str = None) -> dict:
        """Verify domain ownership."""
        results = {
            "domain": domain,
            "verified": False,
            "method": None,
            "message": ""
        }
        
        if method == "email" or (method == "auto" and email):
            email_result = await self._verify_by_email(domain, email)
            if email_result["verified"]:
                return {**results, **email_result}
        
        if method == "token" or (method == "auto" and token):
            token_result = await self._verify_by_token(domain, token)
            if token_result["verified"]:
                return {**results, **token_result}
        
        if method == "auto":
            # Try all methods
            email_result = await self._verify_by_email(domain, email)
            if email_result["verified"]:
                return {**results, **email_result}
            
            token_result = await self._verify_by_token(domain, token)
            if token_result["verified"]:
                return {**results, **token_result}
        
        results["message"] = "Verification failed - no valid verification method found"
        return results
    
    async def _verify_by_email(self, domain: str, email: str) -> dict:
        """Verify by email domain match."""
        if not email:
            return {"verified": False, "message": "No email provided"}
        
        # Extract domain from email
        email_match = re.match(r'[^@]+@(.+)', email)
        if not email_match:
            return {"verified": False, "message": "Invalid email format"}
        
        email_domain = email_match.group(1).lower()
        target_domain = domain.lower()
        
        # Remove www from both
        if email_domain.startswith('www.'):
            email_domain = email_domain[4:]
        if target_domain.startswith('www.'):
            target_domain = target_domain[4:]
        
        # Check exact match or subdomain
        if email_domain == target_domain:
            return {
                "verified": True,
                "method": "email",
                "message": f"Email domain matches target domain"
            }
        
        if email_domain.endswith('.' + target_domain):
            return {
                "verified": True,
                "method": "email",
                "message": f"Email domain is a subdomain of target"
            }
        
        return {
            "verified": False,
            "message": f"Email domain {email_domain} does not match {target_domain}"
        }
    
    async def _verify_by_token(self, domain: str, token: str) -> dict:
        """Verify by token in file or meta tag."""
        if not token:
            return {"verified": False, "message": "No verification token provided"}
        
        # Try verification file
        verification_urls = [
            f"https://{domain}/.crawler-verification.txt",
            f"https://www.{domain}/.crawler-verification.txt",
            f"http://{domain}/.crawler-verification.txt",
            f"http://www.{domain}/.crawler-verification.txt",
        ]
        
        for url in verification_urls:
            try:
                response = await self.http_client.get(url)
                if response.status_code == 200:
                    content = response.text.strip()
                    if token in content:
                        return {
                            "verified": True,
                            "method": "token_file",
                            "message": f"Token found in {url}"
                        }
            except Exception:
                continue
        
        # Try meta tag verification
        meta_urls = [
            f"https://{domain}/",
            f"https://www.{domain}/",
        ]
        
        for url in meta_urls:
            try:
                response = await self.http_client.get(url)
                if response.status_code == 200:
                    content = response.text
                    # Look for meta tag
                    meta_pattern = rf'<meta[^>]+name=["\']crawler-verification["\'][^>]+content=["\']{re.escape(token)}["\']'
                    if re.search(meta_pattern, content, re.IGNORECASE):
                        return {
                            "verified": True,
                            "method": "meta_tag",
                            "message": f"Token found in meta tag at {url}"
                        }
                    
                    # Alternative pattern
                    alt_pattern = rf'<meta[^>]+content=["\']{re.escape(token)}["\'][^>]+name=["\']crawler-verification["\']'
                    if re.search(alt_pattern, content, re.IGNORECASE):
                        return {
                            "verified": True,
                            "method": "meta_tag",
                            "message": f"Token found in meta tag at {url}"
                        }
            except Exception:
                continue
        
        return {
            "verified": False,
            "message": "Token not found in verification file or meta tag"
        }
    
    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()


class TokenVerifier:
    """Verify API tokens for crawl requests."""
    
    def __init__(self):
        self.settings = get_settings()
    
    def generate_verification_token(self, domain: str) -> str:
        """Generate verification token for domain."""
        import hashlib
        import secrets
        
        # Create a random component
        random_part = secrets.token_hex(16)
        
        # Create domain-based hash
        secret = self.settings.verification_token_secret
        domain_hash = hashlib.sha256(
            f"{domain}:{secret}:{random_part}".encode()
        ).hexdigest()[:32]
        
        return f"{random_part}_{domain_hash}"
    
    def validate_token(self, token: str, domain: str) -> bool:
        """Validate verification token."""
        try:
            parts = token.split('_')
            if len(parts) != 2:
                return False
            
            random_part, provided_hash = parts
            
            # Recalculate expected hash
            secret = self.settings.verification_token_secret
            expected_hash = hashlib.sha256(
                f"{domain}:{secret}:{random_part}".encode()
            ).hexdigest()[:32]
            
            return provided_hash == expected_hash
        except Exception:
            return False
