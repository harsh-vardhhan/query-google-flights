from sqlalchemy import create_engine
from langchain_community.utilities import SQLDatabase
from langchain.chains import create_sql_query_chain
from langchain.prompts import PromptTemplate
from sqlite import json_to_sqlite
from query_validator import is_flight_related_query
from llm import get_llm

# Database and LLM setup
url = 'sqlite:///flights.db'
engine = create_engine(url, echo=False)
db = SQLDatabase(engine)
llm = get_llm()

sql_prompt = PromptTemplate(
    input_variables=["input", "top_k", "table_info"],
    template="""Given the following input: {input}

For the database with the following schema:
{table_info}

Generate a SQL query that:
1. Is valid SQLite syntax
2. Returns at most {top_k} results
3. ALWAYS explicitly specify columns instead of using *
4. ALWAYS include price_inr column when price information is relevant
5. Use a consistent column order: date, origin, destination, price_inr, flightType
6. Keep price_inr as raw integer values without any formatting
7. DO NOT modify or transform price values in the query
8. **DO NOT introduce typos like 'price_inn' or any other variations. Only use 'price_inr'.**
9. Returns only the raw SQL query without any formatting or markdown

Example queries:
Good: SELECT date, origin, destination, price_inr, flightType FROM flights WHERE price_inr < 10000
Bad: SELECT date, origin, destination, price_inr/100 as price, flightType FROM flights

Query:"""
)

response_prompt = PromptTemplate(
    input_variables=["question", "sql_query", "query_result"],
    template="""Given the user's question: {question}

The SQL query used: {sql_query}

And the query results: {query_result}

IMPORTANT FORMATTING REQUIREMENTS:

1. Table Format:
   - ALWAYS use markdown table format with | separators
   - Include header row and separator row
   - Right-align price column
   Example:
   | Date | Origin | Destination | Price (₹) | Type |
   |------|--------|------------|----------:|------|
   | 2024-01-15 | Delhi | Mumbai | ₹5,000 | Direct |

2. Price Formatting Rules:
   - Format raw price_inr values as follows:
     * For 4 digits (1000-9999): ₹X,XXX (e.g., 5000 → ₹5,000)
     * For 5 digits (10000-99999): ₹XX,XXX (e.g., 15000 → ₹15,000)
     * For 6 digits (100000-999999): ₹X,XX,XXX (e.g., 150000 → ₹1,50,000)
   - DO NOT add extra digits or commas
   - Examples of correct formatting:
     * 9852 → ₹9,852 (not ₹9,85,252)
     * 98520 → ₹98,520 (not ₹9,85,200)
   - Use exact values from price_inr without modification

3. Column Order:
   - Date (YYYY-MM-DD format)
   - Origin
   - Destination
   - Price (₹)
   - Type

4. Response Structure:
   - Brief answer first
   - Data table
   - Concise analysis of prices, dates, and flight types
   - Clear and conversational tone

Remember:
- Keep raw price values exactly as provided
- Double-check price formatting
- Never add extra digits to prices
- Verify table format before responding

Response:"""
)

async def process_flight_query():
    question = input("Enter your question about flights: ")

    if not is_flight_related_query(question):
        print("\nQuery not related to flight data. Please ask a question about flights, prices, routes, or travel dates.")
        return

    try:
        sql_chain = create_sql_query_chain(llm=llm, db=db, prompt=sql_prompt)
        sql_query = await sql_chain.ainvoke({"question": question})

        def validate_sql_query(sql_query, expected_columns):
            for col in expected_columns:
                if col not in sql_query:
                    raise ValueError(f"Invalid SQL query: Missing column '{col}'")
            return sql_query

        expected_columns = ["date", "origin", "destination", "price_inr", "flightType"]
        cleaned_query = validate_sql_query(sql_query.strip('`').replace('sql\n', '').strip(), expected_columns)
        print(f"\nGenerated SQL Query: {cleaned_query}")

        if cleaned_query:
            query_result = db.run(cleaned_query)
            response_input = {
                "question": question,
                "sql_query": cleaned_query,
                "query_result": query_result
            }
            response = await llm.ainvoke(response_prompt.format(**response_input))
            print("\nFinal Response:")
            print(response.content)
        else:
            print("No SQL query was generated.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    import asyncio
    json_to_sqlite('flight_data.json', 'flights.db')
    while True:
        asyncio.run(process_flight_query())
        if input("\nDo you want to ask another question? (y/n): ").lower() != 'y':
            break