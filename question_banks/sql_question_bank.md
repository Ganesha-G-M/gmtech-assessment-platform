# SQL Assessment Question Bank

SQL fundamentals, joins, aggregation, normalization, transactions, and query reasoning.

## MCQ Set (20 Questions)

1. Which SQL clause filters grouped rows after aggregation?
   A. WHERE
   B. HAVING
   C. GROUP BY
   D. ORDER BY
   Answer: B

2. Which join returns all rows from the left table and matching rows from the right table?
   A. INNER JOIN
   B. LEFT JOIN
   C. RIGHT JOIN
   D. CROSS JOIN
   Answer: B

3. What does COUNT(*) return?
   A. Only non-null values in one column
   B. Total rows in the result set
   C. Distinct rows only
   D. Number of tables
   Answer: B

4. Which command removes all rows from a table while usually keeping its structure?
   A. DROP
   B. TRUNCATE
   C. ALTER
   D. RENAME
   Answer: B

5. Which normal form removes partial dependency on part of a composite key?
   A. 1NF
   B. 2NF
   C. 3NF
   D. BCNF
   Answer: B

6. What is the main purpose of an index?
   A. Encrypt data
   B. Improve lookup speed
   C. Increase table size
   D. Prevent all duplicates
   Answer: B

7. Which SQL keyword removes duplicate rows from a result?
   A. UNIQUE
   B. DISTINCT
   C. ONLY
   D. GROUP
   Answer: B

8. What does a primary key guarantee?
   A. Nullable values
   B. Unique non-null row identification
   C. Only text values
   D. Automatic sorting
   Answer: B

9. Which aggregate function ignores NULL values?
   A. COUNT(column)
   B. COUNT(*)
   C. SELECT *
   D. ORDER BY
   Answer: A

10. Which operator checks whether a value is within a set of values?
   A. LIKE
   B. IN
   C. BETWEEN
   D. EXISTS
   Answer: B

11. Which clause is evaluated logically before SELECT?
   A. ORDER BY
   B. WHERE
   C. LIMIT
   D. Alias display
   Answer: B

12. What does ACID durability mean?
   A. Transactions run quickly
   B. Committed data survives failures
   C. Data is always duplicated
   D. Queries are cached
   Answer: B

13. Which statement changes existing table rows?
   A. INSERT
   B. UPDATE
   C. CREATE
   D. GRANT
   Answer: B

14. Which constraint enforces a relationship to a key in another table?
   A. CHECK
   B. DEFAULT
   C. FOREIGN KEY
   D. NOT NULL
   Answer: C

15. Which query finds rows where email is missing?
   A. email = NULL
   B. email IS NULL
   C. email == NULL
   D. email LIKE NULL
   Answer: B

16. What is a correlated subquery?
   A. A subquery that references the outer query
   B. A query with no WHERE clause
   C. A query using only one table
   D. A query that always returns one row
   Answer: A

17. Which isolation issue happens when the same query returns different row sets during a transaction?
   A. Dirty read
   B. Lost update
   C. Phantom read
   D. Syntax error
   Answer: C

18. Which clause sorts query results?
   A. SORT BY
   B. ORDER BY
   C. GROUP SORT
   D. RANK BY
   Answer: B

19. What does UNION do by default?
   A. Combines results and removes duplicates
   B. Combines results and keeps duplicates
   C. Joins columns horizontally
   D. Deletes duplicate table rows
   Answer: A

20. Which function returns the largest value in a group?
   A. TOP
   B. MAX
   C. LARGEST
   D. HIGH
   Answer: B

## Coding Set (20 Questions)

1. Write a query to return the second highest salary from an Employees table.
2. Write a query to find duplicate email addresses in a Users table.
3. Write a query to list departments with more than five employees.
4. Write a query to return customers who placed no orders.
5. Write a query to calculate monthly revenue from an Orders table.
6. Write a query to find the top three products by total quantity sold.
7. Write a query to update inactive users who have not logged in for 365 days.
8. Write a query to delete exact duplicate rows while keeping the lowest id.
9. Write a query using a window function to rank employees by salary within each department.
10. Write a query to find products whose price is above their category average.
11. Write a query to pivot order counts by status for each customer.
12. Write a query to get running total revenue ordered by order_date.
13. Write a query to find users registered in the last 30 days.
14. Write a query to enforce a unique email constraint on a users table.
15. Write a transaction that transfers money between two accounts safely.
16. Write a query to find the earliest order for each customer.
17. Write a query using CASE to label scores as Pass or Fail.
18. Write a query to return employees whose manager is also in the Employees table.
19. Write a query to find gaps in sequential invoice numbers.
20. Write a query to create a normalized table structure for students, courses, and enrollments.
