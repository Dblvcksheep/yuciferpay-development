**YuciferPay**

***Crypto Merchant Automation • Payroll • Bulk/Scheduled Payouts***


YuciferPay is an automation service platform designed to make crypto payouts, payroll, and bulk/scheduled payments stress-free and simple.

Built with Flask, Python, HTML, and CSS, it provides merchants and businesses a seamless way to handle crypto payouts, payrolls, and scheduled bulk payments.

**Vision**

***Payment automation should be:***

*Simple*: Reduce manual clicks and human error

*Efficient*: Handle crypto and fiat payouts at scale

*Autonomous*: Enable bots to process payouts without manual intervention

*Global*: Expand to multiple countries, banks, and crypto platforms

YuciferPay aims to be the go-to platform for automating merchant and payroll payments worldwide.

**Core Features**

🚀 ***Crypto Merchant Automation***

Automates payouts for crypto merchants

Currently requires manual “check order” and “pay all” clicks

Future updates will enable fully autonomous payouts with a user-controlled toggle

💼 ***Payroll & Salary Automation***

Schedule and process employee salaries

Supports bulk or recurring payments

📆 Bulk & Scheduled Payouts

Automate large-scale payouts for businesses

Schedule recurring payments across multiple accounts

⚡ ***Automation Engine***

Powered by Celery workers and Redis broker

Handles task queueing for efficient payout processing

Future goal: bots fully monitor and execute payments independently

**Tech Stack**

*Backend*:	<mark>Flask</mark>

*Language*:	<mark>Python</mark>

*Frontend*:	<mark>HTML, CSS</mark>

*Task Queue*:	<mark>Celery</mark>

*Broker*:	<mark>Redis</mark>

*Automation*:	<mark>Cron-style scheduling & bots</mark>

**Running the Project**

*Step 1*: Install dependencies

```bash
python -m pip install -r requirements.txt
```

*Step 2*: Set environment variables

```bash
Create a .env file:
FLASK_APP=main.py
```

*Step 3*: Start the server

```bash
flask run
```

**Future Roadmap**

Integration with more crypto P2P platforms

Expand bank coverage and international support

Fully autonomous payout bots

Smart toggles for users to let bots run without manual clicks

Enhanced dashboards and analytics for payments

**Philosophy**

YuciferPay believes financial automation should be simple, stress-free, and secure.
Manual payouts are error-prone and time-consuming; automation ensures reliability and speed.

**Contributing**

***Contributions are welcome! You can help by***:

Adding new crypto or bank integrations

Improving automation bot logic

Enhancing front-end usability

Suggesting features or optimizations

Pull requests and issues are encouraged.

**License**

This project is open-source under the MIT License.
