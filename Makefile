.PHONY: install download extract review test

install:
	pip install -r requirements.txt

# 單一年份:make download YEAR=2025
download:
	python -m src.scraper.download_annual_reports --year $(YEAR)

# 歷史回補,預設抓 1998 到今年全部年份(對每家公司,抓不到的年份是正常現象,見程式說明)
download-all-history:
	python -m src.scraper.download_annual_reports

# 範例:make extract
extract:
	python -m src.extract.run_pipeline --dir data/raw_pdfs --companies-csv config/companies.csv

review:
	streamlit run src/review_app/app.py

test:
	python -m pytest tests/ -v
