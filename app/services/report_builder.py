
from utils.config_utils import init_odoo_cache, init_mongo_dao
from utils.function_utils import build_fields
from data_connectors.sales_service import SalesService
from data_connectors.inventory_service import InventoryService

import io
import math
import pandas as pd
from io import BytesIO, StringIO

output_cols = build_fields("""item_id
itemcode
dscription
day_cover
7d
prev7d
14d
prev14d
s2
s1
ext_wh
categorie
supplier
pcb_achat""")
output_cols_proj=output_cols+['proj7d', 'proj14d','daily_sales_last_6d']


class ReportBuilder:
	def __init__(self, odoo_cache, mongo_dao):
		self.sales_services = SalesService(odoo_cache, mongo_dao)
		self.inventory_service = InventoryService(odoo_cache)
		self.masterdata = self.inventory_service.get_masterdata()

	def output_in_excel(self, outputBuffer, report_data, cutoff=2):
		summary_df, filtered_df = report_data
		# Find a way to configure the threshold between urgent and not urgent suppliers 
		urgent_suppliers = summary_df.query(f"under_{cutoff}day_cover >= 3").supplier.values.tolist()
		not_urgent_suppliers = summary_df.query(f"under_{cutoff}day_cover < 3").supplier.values.tolist()
		apply_format_fn = apply_formats_1
		with pd.ExcelWriter(outputBuffer, engine='xlsxwriter') as writer:
			summary_df.to_excel(writer, sheet_name='summary')
			worksheet = writer.sheets['summary']
			worksheet.set_column('B:B', to_size_col(2.2), None)
			for name in urgent_suppliers:
				dataframe = filtered_df.query(f"supplier==@name").sort_values(by='day_cover').loc[:, output_cols_proj]
				sheetname=name.split(' ')[0]
				write_worksheet(writer, dataframe, sheetname, apply_format_fn)

			other_suppliers = filtered_df.query("supplier in @not_urgent_suppliers")
			write_worksheet(writer, other_suppliers.sort_values(by=['supplier', 'day_cover']).loc[:, output_cols_proj], 'OTHERS', apply_format_fn)


	def output_in_text(self, buffer, report_data):
		summary_df, filtered_df = report_data
		# 1. Create the buffer (using a context manager is best practice)
		# 2. Write to the buffer
		urgent_suppliers = summary_df.query("under_2day_cover >= 3").supplier.values.tolist()
		not_urgent_suppliers = summary_df.query("under_2day_cover < 3").supplier.values.tolist()
		buffer.write("# Critical stock shortage\n")
		buffer.write("## Summary\n")
		buffer.write(summary_df.to_csv(sep=';', index=False))
		buffer.write("\n")

		critical_df = filtered_df.query("day_cover<=10")
		for name in urgent_suppliers:
			dataframe = critical_df.query(f"supplier==@name").sort_values(by='day_cover').loc[:, output_cols_proj]
			buffer.write(f"## {name}\n")
			buffer.write(dataframe.to_csv(sep=';', index=False))
			buffer.write("\n")

		other_suppliers = critical_df.query("supplier in @not_urgent_suppliers")
		buffer.write(f"## Other suppliers\n")
		buffer.write(other_suppliers.sort_values(by=['supplier', 'day_cover']).loc[:, output_cols_proj].to_csv(sep=';', index=False))

		# 3. Retrieve the entire string using getvalue()
		# Note: We use getvalue() instead of read() because read() 
		# requires the cursor to be at the beginning (seek(0)). 
		# getvalue() grabs everything regardless of cursor position.
		entire_string = buffer.getvalue()
		return entire_string



	def compute_report_data(self, strategy, cutoff = "2"):
		trends = self.sales_services.get_sales_and_trends()
		trends_df = self.inventory_service.augment_with_stocks(trends)
		trends_df = self.sales_services.compute_projections(trends_df, self.masterdata, strategy)

		values=['item_id']
		index=['supplier']
		columns=[]
		summary_df = pd.DataFrame(pd.pivot_table(trends_df.query(f"day_cover<=10"), values=values, index=index, columns=columns, aggfunc='count').to_records())\
		.sort_values(by=['item_id'], ascending=False)
		summary_df.rename(columns={'item_id':f"under_{cutoff}day_cover"}, inplace=True)
		return summary_df, trends_df

## functions to output in excel format
def to_size_col(xlsize):
    return int(math.ceil(100*xlsize/9.79))

def build_formats_for(workbook):
    # Add some cell formats.
    format1 = workbook.add_format({'num_format': '#,##0.00', 'valign':'center'})
    format2 = workbook.add_format({'num_format': '0%'})#;[RED] -0%
    format3 = workbook.add_format({'num_format': '#,##0.00 [$€-40C];[RED]-#,##0.00 [$€-40C]'})
    error_fmt = workbook.add_format({'bg_color': '#cc0000','font_color': '#ffffff'})
    neutral_format=workbook.add_format({'bg_color': '#ffffcc','font_color': '#996600'})
    warning_format=workbook.add_format({'bg_color':'#f2cbf8','font_color': '#7c007c'})
    bad_format=workbook.add_format({'bg_color': '#ffcccc','font_color': '#cc0000'})
    good_format=workbook.add_format({'bg_color': '#ccffcc','font_color': '#006600'})
    date_format1 = workbook.add_format({'num_format':'yyyy-mm-dd'})
    stock_col = workbook.add_format({'bg_color': '#729fcf','font_color': '#ffffff', 'valign':'center'})

    fmt_array=[None, format1, format2, format3, neutral_format
               , warning_format, bad_format
               , good_format, error_fmt,date_format1,stock_col]
    fmt_names=["no_format","number", "percents", "currency", "neutral", "warning", "bad", "good", "error", "date1", 'stock_col']
    formats={k:v for k,v in zip(fmt_names, fmt_array)}
    return formats
    
def apply_formats_1(sheetname, worksheet, formats, sizes, rows, columns, dataframe=None):
    worksheet.conditional_format("C2:C{}".format(rows+1)
                                 , {"type":'formula', "criteria":"${sheetname}.$D2<3".format(sheetname=sheetname.upper())
                                 , "format":formats["bad"]})
    for (col, size, fmt) in sizes:
        worksheet.set_column(col, size, formats[fmt])

def write_worksheet(writer, dataframe, sheetname, apply_format_fn):
    resize_cols = [
            ["B:B", to_size_col(0.89), "no_format"]
            ,["C:C", to_size_col(5), "no_format"]
            ,["D:G", to_size_col(1.2), "number"]
            ,["I:I", to_size_col(1.2), "stock_col"]
            ,["J:K", to_size_col(1.2), "number"]
            ,["L:M", to_size_col(2), "no_format"]
    ]
    # Get the xlsxwriter workbook and worksheet objects.
    workbook  = writer.book
    dataframe.to_excel(writer, sheet_name=sheetname, index=False)
    r, c = dataframe.shape # number of rows and columns
    formats = build_formats_for(workbook)
    worksheet = writer.sheets[sheetname]
    worksheet.freeze_panes(1,3)
    worksheet.autofilter(0,0,r,c)
    worksheet.set_zoom(65)
    apply_formats_1(sheetname, worksheet, formats, resize_cols, r, c, dataframe)


