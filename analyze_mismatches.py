import psycopg2
from config import DB_CONFIG


def analyze_mismatches():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        query = """
        select a.id, a.name as master_name, a.country_code as master_country, 
               b.id, b.name as matched_name, b.country_code as matched_country,
               b.match_type, b.match_score
        from p7_firms_v2 a,
             p7_firms_v2 b
        where a.master_code = b.master_code
          and a.match_type = 'NEW_MASTER'
          AND B.match_type != 'NEW_MASTER'
        limit 100;
        """

        cur.execute(query)
        rows = cur.fetchall()

        with open("mismatch_results.txt", "w", encoding="utf-8") as f:
            f.write(
                f"{'Master Name':<45} | {'Matched Name':<45} | {'Type':<15} | {'Score'}\n"
            )
            f.write("-" * 120 + "\n")

            for row in rows:
                f.write(
                    f"{str(row[1])[:43]:<45} | {str(row[4])[:43]:<45} | {row[6]:<15} | {row[7]}\n"
                )

        cur.close()
        conn.close()
        print("mismatch_results.txt created.")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    analyze_mismatches()
