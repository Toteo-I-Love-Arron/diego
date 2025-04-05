import os
import bcrypt
import requests
import time
from dotenv import load_dotenv
from gql import gql, Client
from gql.transport.requests import RequestsHTTPTransport

# Load environment variables from .env file
load_dotenv('token.env')

class SorareBot:
    def __init__(self):
        # Load credentials from environment variables
        self.email = os.getenv("SORARE_EMAIL")
        self.password = os.getenv("SORARE_PASSWORD")
        self.webhook = os.getenv("DISCORD_WEBHOOK")
        
        # Set up the Sorare GraphQL API client (initially without authentication)
        self.client = None

    def _get_salt(self):
        """Retrieve the salt needed for hashing the password from Sorare API"""
        try:
            response = requests.get(
                f"https://api.sorare.com/api/v1/users/{self.email}",
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            return response.json().get("salt")
        except Exception as e:
            print(f"⚠️ Error getting salt: {e}")
            return None
    
    def _authenticate(self):
        """Authenticate with Sorare and retrieve JWT token"""
        salt = self._get_salt()
        if not salt:
            raise Exception("Failed to retrieve salt from Sorare API.")
        
        hashed_pw = bcrypt.hashpw(self.password.encode(), salt.encode()).decode("utf-8")
        
        transport = RequestsHTTPTransport(
            url="https://api.sorare.com/graphql",
            headers={"Content-Type": "application/json"}
        )
        
        temp_client = Client(transport=transport)
        
        result = temp_client.execute(
            gql("""
            mutation SignIn($input: signInInput!, $aud: String!) {
                signIn(input: $input) {
                    jwtToken(aud: $aud) { token }
                    errors { message }
                }
            }
            """),
            variable_values={
                "input": {
                    "email": self.email,
                    "password": hashed_pw
                },
                "aud": "sorare-bot"
            }
        )
        
        if errors := result.get("signIn", {}).get("errors"):
            raise Exception(f"Auth failed: {errors}")
            
        self.client = Client(transport=RequestsHTTPTransport(
            url="https://api.sorare.com/graphql",
            headers={
                "Authorization": f"Bearer {result['signIn']['jwtToken']['token']}",
                "JWT-AUD": "sorare-bot",
                "Content-Type": "application/json"
            }
        ))

    def _send_alert(self, message):
        """Send notification to Discord"""
        try:
            requests.post(
                self.webhook,
                json={"content": message},
                timeout=5
            )
        except Exception as e:
            print(f"⚠️ Failed to send Discord alert: {e}")

    def _fetch_listings(self):
        """Fetch latest listed cards"""
        query = gql("""
            query {
              football {
                cards(first: 5, listed: true) {
                  nodes {
                    slug
                    player {
                      displayName
                    }
                    saleOffers(first: 1) {
                      edges {
                        node {
                          price {
                            amount
                            currency
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
        """)

        try:
            result = self.client.execute(query)
            print("API Response:", result)  # Debug API response
        except Exception as e:
            print(f"⚠️ API request failed: {e}")
            self._send_alert(f"⚠️ API request failed: {e}")
            return []

        listings = []
        for card in result.get("football", {}).get("cards", {}).get("nodes", []):
            price_data = card.get("saleOffers", {}).get("edges", [])
            price = price_data[0]["node"]["price"]["amount"] if price_data else "N/A"
            currency = price_data[0]["node"]["price"]["currency"] if price_data else "N/A"

            listings.append({
                "slug": card["slug"],
                "price": price,
                "currency": currency,
                "player": card["player"]["displayName"]
            })

        return listings

    def run(self):
        """Main execution loop"""
        try:
            self._authenticate()
            self._send_alert("🟢 Sorare Bot Started Successfully")
            print("🟢 Bot is running...")
            
            while True:
                try:
                    listings = self._fetch_listings()
                    for card in listings:
                        message = (
                            f"⚽ {card['player']}\n"
                            f"💰 {card['price']} {card['currency']}\n"
                            f"🔗 https://sorare.com/cards/{card['slug']}"
                        )
                        print(message)
                        self._send_alert(message)

                    time.sleep(300)  # Wait 5 minutes before fetching again
                    
                except Exception as e:
                    error_msg = f"⚠️ Unexpected error: {str(e)}"
                    print(error_msg)
                    self._send_alert(error_msg)
                    time.sleep(60)  # Wait before retry

        except Exception as e:
            error_msg = f"🔴 Critical failure: {str(e)}"
            print(error_msg)
            self._send_alert(error_msg)

if __name__ == "__main__":
    bot = SorareBot()
    bot.run()
