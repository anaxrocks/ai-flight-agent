import requests
import json
from datetime import datetime

hotels_url = "https://booking-com.p.rapidapi.com/v2/hotels/search-by-coordinates"
flights_url = 'https://booking-com15.p.rapidapi.com/api/v1/flights/searchFlights'
headers = {
    "x-rapidapi-host": "booking-com.p.rapidapi.com",
    "x-rapidapi-key": "8d25d47055msh2047eaa47c94e13p1279efjsn1570d7c57cb7"  # Replace with your API key
}

def process_hotel_data(data):
    # Create a list to store the results
    processed_results = []
    
    # Get the first 10 results
    for hotel in data['results'][:8]:
        # Extract relevant information for each hotel
        hotel_info = {
            'name': hotel['name'],
            'price': hotel['priceBreakdown']['grossPrice']['value'],  # The gross price
            'checkin': hotel.get('checkin', 'Not Available'),  # Example, adjust based on the response structure
            'checkout': hotel.get('checkout', 'Not Available'),  # Example, adjust based on the response structure
            'review_score': hotel.get('reviewScore', 'Not Available')  # Example, adjust based on the response structure
        }
        
        processed_results.append(hotel_info)
    
    # Return the processed results
    return processed_results

def search_hotels(**kwargs):
    """
    Search for hotels using exact parameter format required by the API.
    Example format:
    {
        "categories_filter_ids": "class::2,class::4,free_cancellation::1",
        "children_number": 2,
        "page_number": 0,
        "latitude": 40.776676,
        "longitude": -73.971321,
        "checkout_date": "2025-03-17",
        "units": "metric",
        "locale": "en-gb",
        "checkin_date": "2025-03-16",
        "include_adjacency": "true",
        "room_number": 1,
        "order_by": "popularity",
        "children_ages": "5,0",
        "filter_by_currency": "USD",
        "adults_number": 2
    }
    """
    # Ensure all parameters are in the exact format required
    params = {
        "categories_filter_ids": "class::2,class::4,free_cancellation::1",
        "children_number": int(kwargs.get('children_number', 0)),
        "page_number": 0,
        "latitude": float(kwargs.get('latitude')),
        "longitude": float(kwargs.get('longitude')),
        "checkout_date": kwargs.get('checkout_date'),
        "units": "metric",
        "locale": "en-gb",
        "checkin_date": kwargs.get('checkin_date'),
        "include_adjacency": "true",
        "room_number": int(kwargs.get('room_number', 1)),
        "order_by": "popularity",
        "children_ages": kwargs.get('children_ages', ''),
        "filter_by_currency": "USD",
        "adults_number": int(kwargs.get('adults_number', 1))
    }

    response = requests.get(hotels_url, headers=headers, params=params)
                
    if response.status_code == 200:
        data = response.json()
        processed_data = process_hotel_data(data)
        # Save the entire processed data as a JSON file
        with open('hotel_options.json', 'w') as json_file:
            json.dump(processed_data, json_file, indent=4)
    else:
        print(f"Error: {response.status_code}")
        print(response.text)

def process_flight_data(raw_data):
    """
    Process raw flight data JSON and extract key information for each flight.
    
    Args:
        raw_data (dict): The raw flight data JSON object
        
    Returns:
        list: A list of dictionaries containing processed flight information
    """
    processed_flights = []
    
    # Check if data is valid
    if not raw_data.get("status") or not raw_data.get("data") or not raw_data["data"].get("flightOffers"):
        return processed_flights
    
    # Process each flight offer
    for offer in raw_data["data"]["flightOffers"][:5]:
        # Look for price information specific to this offer
        # Note: In the snippet provided, individual offer prices weren't visible,
        # so this might need adjustment based on the complete data structure
        offer_price = None
        if offer.get("price"):
            offer_price = {
                "currency": offer.get("price", {}).get("currencyCode", "USD"),
                "amount": offer.get("price", {}).get("units", 0) + 
                         (offer.get("price", {}).get("nanos", 0) / 1_000_000_000)
            }
        
        for segment in offer.get("segments", []):
            # Extract basic flight information
            flight_info = {
                # Route information
                "departure_airport": segment["departureAirport"]["code"],
                "arrival_airport": segment["arrivalAirport"]["code"],
                
                # Time information
                "departure_time": segment["departureTime"],
                "arrival_time": segment["arrivalTime"],
                
                # Flight details
                "stops": len(segment.get("legs", [])) - 1 if segment.get("legs") else 0,
            }
            
            # Process legs to get more detailed information
            if segment.get("legs"):
                leg = segment["legs"][0]  # Using first leg for direct flights or first leg info
                
                # Add airline information
                if leg.get("carriersData") and len(leg["carriersData"]) > 0:
                    carrier_data = leg["carriersData"][0]
                    flight_info["airline_code"] = carrier_data.get("code", "")
                    flight_info["airline_name"] = carrier_data.get("name", "")
                    flight_info["airline_logo"] = carrier_data.get("logo", "")
                
                # Add flight number if available
                if leg.get("flightInfo") and leg["flightInfo"].get("flightNumber"):
                    flight_info["flight_number"] = leg["flightInfo"]["flightNumber"]
                
                # Add cabin class
                flight_info["cabin_class"] = leg.get("cabinClass", "")
                
                # Calculate duration in hours and minutes
                if leg.get("totalTime"):
                    total_minutes = leg["totalTime"] // 60
                    hours = total_minutes // 60
                    minutes = total_minutes % 60
                    flight_info["duration"] = f"{hours}h {minutes}m"
                
                # Add terminal information
                flight_info["departure_terminal"] = leg.get("departureTerminal", "")
                flight_info["arrival_terminal"] = leg.get("arrivalTerminal", "")
            
            # Add the price specific to this offer if available
            if offer_price:
                flight_info["price"] = offer_price
            
            # Look for airline-specific pricing in the aggregation data as a fallback
            # This is still not ideal but better than using the global minimum
            elif flight_info.get("airline_code") and raw_data["data"].get("aggregation"):
                for airline in raw_data["data"]["aggregation"].get("airlines", []):
                    if airline.get("iataCode") == flight_info["airline_code"] and airline.get("minPrice"):
                        flight_info["price"] = {
                            "currency": airline["minPrice"].get("currencyCode", "USD"),
                            "amount": airline["minPrice"].get("units", 0) + 
                                     (airline["minPrice"].get("nanos", 0) / 1_000_000_000)
                        }
                        break
            
            processed_flights.append(flight_info)
    
    return processed_flights


def format_datetime(datetime_str):
    """Convert datetime string to a more readable format."""
    if datetime_str:
        try:
            date_obj = datetime.strptime(datetime_str, '%Y-%m-%dT%H:%M:%S')
            return date_obj.strftime("%B %d, %Y %H:%M")
        except ValueError:
            return None
    return None


def search_flights(from_id, to_id, depart_date, return_date, page_no, adults, children, sort, cabin_class, currency_code):    
    # Set up headers
    headers = {
        'x-rapidapi-host': 'booking-com15.p.rapidapi.com',
        'x-rapidapi-key': '8d25d47055msh2047eaa47c94e13p1279efjsn1570d7c57cb7'
    }

    # Set up query parameters
    params = {
        'fromId': from_id,
        'toId': to_id,
        'departDate': depart_date,  # Add departure date
        'returnDate': return_date,  # Add return date for round-trip
        'pageNo': page_no,
        'adults': adults,
        'children': children,
        'sort': sort,
        'cabinClass': cabin_class,
        'currency_code': currency_code
    }

    try:
        # Make the GET request
        response = requests.get(flights_url, headers=headers, params=params)

        # If the request was successful, print the response
        if response.status_code == 200:
            flight_data = response.json()  # Print the entire response for now
            flight_options = process_flight_data(flight_data)
            with open('flight_options.json', 'w') as json_file:
                json.dump(flight_options, json_file, indent=4)
        else:
            print(f"Error: {response.status_code} - {response.text}")

    except requests.exceptions.RequestException as e:
        print(f"Error: {str(e)}")