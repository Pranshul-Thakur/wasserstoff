#write 

import asyncio
import logging
from playwright.async_api import async_playwright
from dataclasses import dataclass
import json
import time

# Set up basic logging to see what's happening during execution
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define a dataclass to store profile information
@dataclass
class LinkedInProfile:
    """
    Stores basic information about a LinkedIn profile.
    
    Attributes:
        name: The person's full name
        profile_url: URL to their LinkedIn profile
        headline: Professional headline/title
        location: Geographic location
    """
    name: str
    profile_url: str
    headline: str = ""
    location: str = ""
    
class SimpleLinkedInScraper:
    """
    A straightforward LinkedIn profile scraper that searches for profiles
    based on keywords and extracts basic information.
    """
    
    def __init__(self, headless=True):
        """
        Initialize the scraper.
        
        Args:
            headless: If True, browser runs in background; if False, browser is visible
        """
        self.headless = headless
        self.profiles = []
        
    async def login(self, page, email, password):
        """
        Log in to LinkedIn with provided credentials.
        
        Args:
            page: Playwright page object
            email: LinkedIn account email
            password: LinkedIn account password
            
        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Navigate to login page
            await page.goto("https://www.linkedin.com/login")
            
            # Fill in login form
            await page.fill("#username", email)
            await page.fill("#password", password)
            
            # Click submit and wait for navigation
            await page.click("button[type='submit']")
            
            # Wait for page to load - more generic approach
            await page.wait_for_load_state("networkidle")
            
            # Check for login success by looking for feed, profile icon, or other common elements
            # Use multiple selectors to increase chances of finding something
            login_success = False
            for selector in [
                "div.feed-identity-module",       # Feed identity module
                "div.global-nav__me",             # Profile icon
                "input[placeholder='Search']",    # Search bar
                "li.global-nav__primary-item",    # Nav menu items
                "div.search-global-typeahead"     # Another search element
            ]:
                if await page.query_selector(selector):
                    login_success = True
                    break
            
            if login_success:
                logger.info("Successfully logged in to LinkedIn")
                # Take a brief pause to let the page fully render
                await asyncio.sleep(2)
                return True
            else:
                logger.error("Could not confirm successful login")
                return False
            
        except Exception as e:
            logger.error(f"Login failed: {str(e)}")
            return False
    
    async def search_profiles(self, page, keyword, max_pages=3):
        """
        Search for LinkedIn profiles based on keyword and collect profile URLs.
        
        Args:
            page: Playwright page object
            keyword: Search term for finding profiles
            max_pages: Maximum number of search result pages to process
            
        Returns:
            list: List of profile URLs found
        """
        profile_urls = []
        
        try:
            # Create search URL with properly encoded keyword
            search_url = f"https://www.linkedin.com/search/results/people/?keywords={keyword.replace(' ', '%20')}"
            await page.goto(search_url)
            
            # Wait for search results to load with a more robust approach
            selectors = [
                "ul.reusable-search__entity-result-list",  # Main results list
                "div.search-results-container",            # Results container
                "div.search-results"                       # Another results container
            ]
            
            found = False
            for selector in selectors:
                try:
                    await page.wait_for_selector(selector, timeout=5000)
                    found = True
                    break
                except:
                    continue
                    
            if not found:
                logger.warning(f"Could not find search results for '{keyword}'")
                # Take a screenshot to help debug
                await page.screenshot(path=f"search_debug_{keyword.replace(' ', '_')}.png")
                return profile_urls
            
            # Process each page of search results up to max_pages
            for current_page in range(1, max_pages + 1):
                logger.info(f"Processing search page {current_page} for '{keyword}'")
                
                # Wait a moment for dynamic content to load
                await asyncio.sleep(2)
                
                # Try multiple selectors for profile cards
                profile_card_selectors = [
                    "li.reusable-search__result-container",
                    "li.search-result",
                    "div.entity-result"
                ]
                
                profile_cards = []
                for selector in profile_card_selectors:
                    cards = await page.query_selector_all(selector)
                    if cards:
                        profile_cards = cards
                        break
                
                # Extract profile URLs
                for card in profile_cards:
                    # Try multiple selectors for profile links
                    link_selectors = [
                        "span.entity-result__title-text a",
                        "a.app-aware-link",
                        "a[data-control-name='search_srp_result']"
                    ]
                    
                    profile_link = None
                    for selector in link_selectors:
                        link = await card.query_selector(selector)
                        if link:
                            profile_link = link
                            break
                    
                    if profile_link:
                        href = await profile_link.get_attribute("href")
                        if href:
                            # Clean URL by removing tracking parameters
                            profile_url = href.split("?")[0]
                            if "/in/" in profile_url and profile_url not in profile_urls:
                                profile_urls.append(profile_url)
                
                # Try to find next button with multiple selectors
                next_button = None
                next_button_selectors = [
                    "button[aria-label='Next']",
                    "button.artdeco-pagination__button--next",
                    "li.artdeco-pagination__button--next button"
                ]
                
                for selector in next_button_selectors:
                    button = await page.query_selector(selector)
                    if button:
                        next_button = button
                        break
                
                # Check if we can move to next page
                if next_button and not (await next_button.is_disabled() if next_button else True) and current_page < max_pages:
                    await next_button.click()
                    await page.wait_for_load_state("networkidle")
                    await asyncio.sleep(3)  # Slightly longer delay between pages
                else:
                    break
                    
            logger.info(f"Found {len(profile_urls)} profile URLs for '{keyword}'")
            return profile_urls
            
        except Exception as e:
            logger.error(f"Error searching for '{keyword}': {str(e)}")
            # Take error screenshot
            try:
                await page.screenshot(path=f"error_search_{keyword.replace(' ', '_')}.png")
            except:
                pass
            return profile_urls
    
    async def scrape_profile(self, page, profile_url):
        """
        Extract basic information from a LinkedIn profile.
        
        Args:
            page: Playwright page object
            profile_url: URL of the LinkedIn profile to scrape
            
        Returns:
            LinkedInProfile: Profile data object or None if an error occurs
        """
        try:
            logger.info(f"Visiting: {profile_url}")
            
            # Navigate to profile page
            await page.goto(profile_url)
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)  # Give page time to fully render
            
            # Try multiple selectors for each field to increase chances of finding data
            name = ""
            name_selectors = [
                "h1.text-heading-xlarge", 
                "h1.inline", 
                "h1.pv-top-card-section__name",
                "h1.text-heading-large"
            ]
            
            for selector in name_selectors:
                element = await page.query_selector(selector)
                if element:
                    name = await element.inner_text()
                    break
            
            headline = ""
            headline_selectors = [
                "div.text-body-medium", 
                "h2.mt1", 
                "h2.pv-top-card-section__headline",
                "div.pv-text-details__left-panel"
            ]
            
            for selector in headline_selectors:
                element = await page.query_selector(selector)
                if element:
                    headline = await element.inner_text()
                    break
            
            location = ""
            location_selectors = [
                "span.text-body-small:has-text('Location')",
                "li.pv-top-card-v2-section__location",
                "span.pv-top-card-section__location",
                "span.text-body-small"
            ]
            
            for selector in location_selectors:
                element = await page.query_selector(selector)
                if element:
                    location = await element.inner_text()
                    break
            
            # Create profile object with cleaned data
            profile = LinkedInProfile(
                name=name.strip() if name else "Unknown",
                profile_url=profile_url,
                headline=headline.strip() if headline else "",
                location=location.strip() if location else ""
            )
            
            return profile
            
        except Exception as e:
            logger.error(f"Error scraping profile {profile_url}: {str(e)}")
            # Take error screenshot
            try:
                await page.screenshot(path=f"error_profile_{profile_url.split('/')[-1]}.png")
            except:
                pass
            return None
    
    async def run(self, email, password, keywords, profiles_per_keyword=5):
        """
        Main function to execute the scraping process.
        
        Args:
            email: LinkedIn account email
            password: LinkedIn account password
            keywords: List of search terms to find profiles
            profiles_per_keyword: Maximum number of profiles to scrape per keyword
        """
        # Start Playwright and launch browser
        async with async_playwright() as playwright:
            # Launch browser with slightly modified options for better stability
            browser = await playwright.chromium.launch(
                headless=self.headless,
                args=['--disable-blink-features=AutomationControlled']  # Hide automation
            )
            
            # Set up context with more realistic browser profile
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            
            # Create page and set longer timeouts
            page = await context.new_page()
            page.set_default_timeout(30000)  # 30 seconds
            
            # Login to LinkedIn
            if not await self.login(page, email, password):
                logger.error("Failed to log in. Exiting.")
                # Save a screenshot of failed login
                await page.screenshot(path="login_failed.png")
                await browser.close()
                return
            
            # Process each search keyword
            for keyword in keywords:
                # Search for profiles
                profile_urls = await self.search_profiles(page, keyword)
                
                # Limit number of profiles to scrape per keyword
                profile_urls = profile_urls[:profiles_per_keyword]
                
                # Visit and scrape each profile
                for url in profile_urls:
                    profile = await self.scrape_profile(page, url)
                    if profile:
                        self.profiles.append(profile)
                        logger.info(f"Successfully scraped: {profile.name}")
                    
                    # Add random delay between profile visits
                    await asyncio.sleep(2 + (2 * asyncio.get_event_loop().time() % 3))
            
            # Clean up by closing the browser
            await browser.close()
    
    def save_profiles(self, filename="linkedin_profiles.json"):
        """
        Save collected profiles to a JSON file.
        
        Args:
            filename: Path to save the JSON output
        """
        with open(filename, 'w') as f:
            # Convert profile objects to dictionaries for JSON serialization
            json.dump({"profiles": [
                {
                    "name": p.name,
                    "profile_url": p.profile_url,
                    "headline": p.headline,
                    "location": p.location
                } for p in self.profiles
            ]}, f, indent=2)
        logger.info(f"Saved {len(self.profiles)} profiles to {filename}")

async def main():
    """
    Entry point function that configures and runs the scraper.
    
    This demonstrates how to use the SimpleLinkedInScraper class.
    """
    # LinkedIn credentials - REPLACE THESE WITH YOUR OWN
    email = "pranshulthakur.11@gmail.com"  # Your LinkedIn login email
    password = "P@9356308775"         # Your LinkedIn password
    
    # Keywords to search for - customize based on your needs
    keywords = ["software developer", "data analyst"]
    
    # Create and configure the scraper
    scraper = SimpleLinkedInScraper(headless=False)  # Set to False to see the browser
    
    # Run the scraper
    await scraper.run(email, password, keywords, profiles_per_keyword=5)
    
    # Save the results to a file
    scraper.save_profiles()
    
    # Print summary
    print(f"Scraped {len(scraper.profiles)} profiles successfully!")

# Standard Python idiom to run the main function when script is executed directly
if __name__ == "__main__":
    asyncio.run(main())