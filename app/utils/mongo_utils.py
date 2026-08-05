import pymongo
import functools
import pandas as pd
import numpy as np
import itertools
import datetime as dt
from utils.function_utils import _map, _eq, _filter, get_values
from utils import function_utils as od
from collections import namedtuple

MongoConfig = namedtuple('MongoConfig', ['config','sorting_id', 'date_format'])
def reset_to_midnight(date: dt.datetime) -> dt.datetime:
    params = ["hour", "minute", "second", "microsecond"]
    return date.replace(**{k:0 for k in params})

def build_mongo_configuration(env_config):
    mongo_fields = ['MONGO_USER', 'MONGO_PASSWORD', 'MONGO_HOST', 'MONGO_DATABASE']
    mg_collection = ['MONGO_STOCK_COLLECTION']
    mg_keys = od.build_fields("""MONGO_URI
MONGO_DATABASE
MONGO_COLLECTION""")
    mgconf = od.takes(*(mongo_fields+mg_collection))(env_config)
    
    mg_values = od.build_fields(f"""mongodb://{mgconf['MONGO_USER']}:{mgconf['MONGO_PASSWORD']}@{mgconf['MONGO_HOST']}:27017
{mgconf['MONGO_DATABASE']}
{mgconf['MONGO_STOCK_COLLECTION']}""")
    return MongoConfig({k:v for k,v in zip(mg_keys, mg_values)}, 'smid', "%Y-%m-%d %H:%M")

def getMondayOf(dtDate) -> dt.datetime:
    isocalendar = dtDate.isocalendar()
    year=isocalendar[0]
    week=isocalendar[1]
    monday=dt.datetime.strptime("{}-W{}".format(year,week)+'-1',"%Y-W%W-%w")
    previous_monday=monday - dt.timedelta(days=7)
    result_monday=monday
    if dtDate<monday:
        result_monday = previous_monday
    return result_monday

def getStartDateOfPeriod(from_date, periodInDays) -> dt.datetime:
    timedelta = dt.timedelta(weeks=periodInDays)
    return getMondayOf(from_date-timedelta)

def build_label(values, columns):
    return ["('sum', '{}', '{}')".format(x[0], x[1]) for x in itertools.product(values, columns)]

def build_pivot_labels(fields, years, months):
    return ["('{}', {}, {})".format(x[0], x[1], x[2])for x in itertools.product(fields, years, months)]

def compute_months_dict_betweenDates(fromDate, toDate):
    months={}
    fromYear = fromDate.year
    toYear = toDate.year
    nbYears = toYear-fromYear+1
    if nbYears==1:
        months[fromYear]=list(range(fromDate.month, toDate.month+1))
    elif nbYears==2:
        months[fromYear]=list(range(fromDate.month, 13))
        months[toYear]=list(range(1, toDate.month+1))
    elif nbYears>2:
        fullYears=list(range(fromYear+1, toYear))
        months[fromYear]=list(range(fromDate.month, 13))
        for year in fullYears:
            months[year]=list(range(1,13))
        months[toYear]=list(range(1, toDate.month+1))
    return months
def convertSerieToDataArray(serie):
    # convert timestamp to unix time and round value to 2 decimals
    # 
    return [[int(x.value/10**6),float(round(y,2)) if y==y else None] for x,y in serie.items()]

def last_docnum(sorting_id: str, date_format: str, from_date: dt.datetime):
    pipeline = [
        {"$match":{"docdate":{"$gt":from_date}}},
        {"$project":{sorting_id:1, "docnum":1, "timestamp":{"$dateToString": {"format":date_format, "date":"$docdate"}}}},
        {"$sort":{sorting_id:pymongo.DESCENDING}},
        {"$limit":1}
    ]
    options={}
    return pipeline, options
    
def customer_sales_within_period(cardcode, periodInWeeks):
    today = reset_to_midnight(dt.datetime.now())
    start_date = getStartDateOfPeriod(today, periodInWeeks)
    query = {"$and":[{"partner_id": cardcode}, {"docdate":{"$gte":start_date}}]}
    return query

def sales_for_items_between_dates(itemcodes, fromDate, toDate):
    query={"$and":[{"item_id":{"$in": itemcodes}}, {"docdate":{"$gte":fromDate}}, {"docdate":{"$lte": toDate}}]}
    return query

def get_historical_sales_for_itemcode(itemcode:dict, from_date: dt.datetime, to_date: dt.datetime):
    # itemcode shape : {"itemcode": itemcode} or {"id": itemcode}
    pipeline = [
        {"$match":{"$and": [itemcode, {"docdate":{"$gte":from_date}}, {"docdate":{"$lte":to_date}}]}},
        {"$project":{"cardname":1, "quantity":1, "year":{"$year":"$docdate"}, "month":{"$month":"$docdate"}}},
    ]
    options={}
    return pipeline, options

def stock_moves_for_itemcodes(itemcodes, from_date: dt.datetime, to_date: dt.datetime):
    projected_f = ["_id", "item_id","partner_id", "itemcode", "dscription", "quantity", "docnum"]
    pipeline = [
        {"$match":{"$and": [{"item_id":{"$in": itemcodes}}, {"docdate":{"$gte":from_date}}, {"docdate":{"$lte":to_date}}]}},
        {"$project": {k:v for k,v in zip(projected_f, [0]+[1]*(len(projected_f)-1))}|
         {"timestamp":{"$dateToString": {"format":"%Y-%m-%d", "date":"$docdate"}}}},
    ]
    options={}
    return pipeline, options

class CacheDao:
    keys = ["MONGO_URI", "MONGO_DATABASE", "MONGO_COLLECTION"]
    URI, DB, COLLECTION = keys
    DATE_FMT="%Y-%m-%d"

    def __init__(self, odoo_cache) -> None:
        self._odoo_cache = odoo_cache
        self._odoo_items = self._odoo_cache.items.values()
    
    def init_app(self, app) -> None:
        self.config={k:v for k,v in map(lambda k: (k, app.config[k]), self.keys)}
        self._sorting_id = app.sorting_id
        self._date_format = app.date_format
        self._client = pymongo.MongoClient(self.config[self.URI])
    def get_client(self):
        return self._client

    def get_collection(self):
        mg_client = self.get_client()
        return self._get_collection_from_dao(mg_client)
        
    def _get_collection_from_dao(self, client):
        return client[self.config[self.DB]][self.config[self.COLLECTION]]

    def find_one_and_update(self, query, update_data):
        '''
        query a dictionary specifying the query to be performed OR any other type to be used as the value for a query for "_id"
        update_data is of shape {'field_1':value, 'field_2':value, ...}
        '''
        collection = self.get_collection()
        return collection.find_one_and_udpate(query, {'$set': update_data})
        
    def find_query(self, query) -> pd.DataFrame:
        foundData = self.with_collection(lambda data: data.find(query))
        return pd.DataFrame(foundData)

    def apply_aggregate(self, pipeline, options):
        foundData = self.with_collection(lambda data: data.aggregate(pipeline))
        return foundData

    def with_collection(self, computation) -> pd.DataFrame:
        collection_data = self.get_collection()
        result = computation(collection_data)
        return result

    def deleteFromQuery(self, query) -> None:
        result = self.with_collection(lambda data: data.delete_many(query))
        print(result.deleted_count)

    def last_record(self):
        sinceDate=dt.datetime.now()-dt.timedelta(weeks=8)
        docnum_obj = list(self.apply_aggregate(*last_docnum(self._sorting_id, self._date_format, sinceDate)))
        if len(docnum_obj)>0:
            value = docnum_obj[0].pop('_id', None)
        return docnum_obj[0] 

    def getSalesForItems(self, itemcodes, fromDate, toDate):
        return self.find_query(sales_for_items_between_dates(itemcodes, fromDate, toDate))

    def importFromData(self, data_to_import):
        self.get_collection().insert_many(data_to_import)

    def getSalesStatsforItem(self, itemcode, fromDate, toDate, movingAvg=0):
        df =pd.DataFrame(self.apply_aggregate(*stock_moves_daily_for_item(itemcode, fromDate, toDate)))
        if not df.empty:
            columns_renamed={"_id":'docdate'}
            outputDf = df.rename(columns=columns_renamed)
            df = outputDf.sort_values(by=["docdate"])
            df['docdate'] = [pd.to_datetime(r.docdate) for r in df.itertuples()]
            result = {}
            output_cols = ["docdate","quantity"]
            value_to_plot="quantity"
            masterdata = mongo_dao._odoo_items
            itemcodes=[itemcode]
            for code in itemcodes:
                ydata=df.loc[:,output_cols].set_index("docdate")
                start = ydata.index[0]
                end = ydata.index[-1]
                X = pd.date_range(start, end, freq='D')
                Y = pd.Series(ydata[value_to_plot], index=X)
                item_data = od._filter_(masterdata, [take('default_code'), od._eq(code)])
                data = convertSerieToDataArray(Y)
                if movingAvg>1:
                    data = convertSerieToDataArray(Y.fillna(0.0).rolling(window=movingAvg).mean())
                result[code] = {"itemname": item_data[0]['name'],"data": data}
            return result[itemcode]
        else:
            return {}


    def getItemsBoughtByClient(self, cardcode, periodInWeeks):
        df = self.find_query(customer_sales_within_period(cardcode, periodInWeeks))
        if df.empty :
            return df
        else:          
            masterdata = pd.DataFrame([{k:v for k,v in zip(['itemcode', 'onhand', 'categorie'], row)} for row in 
                                       _map(get_values(['default_code', 'onhand', 'categ_id.1']), self._odoo_items)])
            df["c"]=[getMondayOf(row.docdate).strftime(self.DATE_FMT) for row in df.itertuples()]
            index_fields=["itemcode", "dscription"]
            values_fields=["quantity"]
            columns_fields=["c"]
            NB_WEEKS=4
            pvdf = pd.pivot_table(df, index=index_fields,values=values_fields, columns=columns_fields,aggfunc=['sum'], fill_value=0)
            outputDf=pd.DataFrame(pvdf.to_records())
            column_labels = df["c"].unique().tolist()
            column_labels.sort(reverse=True)
            labels_count=len(column_labels)
            ind_fields_count=len(index_fields)
            shortened_col_labels = list(map(lambda x:x[5:],column_labels))
            columns_renamed = {k:v for k,v in zip(build_label(values_fields, column_labels), shortened_col_labels)}
            added_displayed_cols = ["occurences", "total","moy"]
            outputDf = outputDf.rename(columns=columns_renamed)
            if NB_WEEKS<labels_count:
              last_weeks_label="last{}w".format(NB_WEEKS)
              outputDf[last_weeks_label]=[functools.reduce(lambda a,b:a+b, map(lambda x: 1 if row[x]>0 else 0, range(ind_fields_count+labels_count-NB_WEEKS,ind_fields_count+labels_count))) for row in outputDf.itertuples(index=False)]
              added_displayed_cols = [last_weeks_label] + added_displayed_cols
            outputDf["occurences"]=[functools.reduce(lambda a,b:a+b, map(lambda x: 1 if row[x]>0 else 0, range(ind_fields_count,ind_fields_count+labels_count))) for row in outputDf.itertuples(index=False)]
            outputDf["total"]=outputDf.loc[:,shortened_col_labels].sum(axis=1)
            outputDf["moy"]=outputDf["total"]/outputDf["occurences"]
            outputDf = outputDf.sort_values(["occurences"], ascending=[0])
            out_cols=[*index_fields, "onhand",*shortened_col_labels,*added_displayed_cols,"categorie"]
            merged = pd.merge(outputDf.loc[:,index_fields+shortened_col_labels+added_displayed_cols], masterdata.loc[:,["itemcode", "onhand","categorie"]],on=["itemcode"])
            #
            return merged.loc[:, out_cols]

    def compute_sales_for_itemcode(self, itemcode, fromDate, toDate):
        pd.set_option('future.no_silent_downcasting', True)
        df = pd.DataFrame(self.apply_aggregate(*get_historical_sales_for_itemcode(itemcode, fromDate, toDate)))
        if df.empty:
            return df
        else:
            periods = compute_months_dict_betweenDates(fromDate,toDate)
            index_fields = ["cardname"]
            values_fields = ['quantity']
            columns_fields = ['year','month']
            pvtable = pd.pivot_table(df, index=index_fields,
            values=values_fields,
            columns=columns_fields,
            aggfunc="sum",
            fill_value=0)
            df1 = pd.DataFrame(pvtable.to_records())
            date_labels=[]
            for (y,m) in periods.items():
                date_labels = date_labels + ["{}-{}".format(str(x[0]),str(x[1]).zfill(2)) for x in itertools.product([y], m)]

            quantity_labels = []
            for (y,m) in periods.items():
                quantity_labels = quantity_labels + build_pivot_labels(["quantity"], [y], m)

            df1 = df1.rename(columns={k:v for (k,v) in zip(quantity_labels, date_labels)})
            df_columns = df1.columns.values.tolist() 
            for date in date_labels:
                if date not in df_columns:
                    df1[date]=0

            dates = df1.columns.tolist()[1:]
            dates.sort(reverse=True)
            df1["total"]=df1.loc[:,date_labels].sum(axis=1)
            cols = ["total"]+date_labels
            ALL_CLIENTS_LABEL = " TOTAL CLIENTS"
            row_to_insert = pd.Series([ALL_CLIENTS_LABEL]+[df1[x].sum() for x in cols], index=["cardname"]+cols)
            result_df = pd.concat([df1, row_to_insert.to_frame().T], ignore_index=True)
            result_df["freq"]=result_df.loc[:,date_labels].gt(0).sum(axis=1)
            past_months=dates[1:]
            result_df["moy"] = result_df.loc[:,past_months].replace(0, np.nan).mean(axis=1, skipna=True)
            result_df["moy"] = result_df["moy"].replace(0, np.nan)
            result_df["remplis."]=(result_df[dates[0]]-result_df["moy"])/result_df["moy"]
            result_df=result_df.sort_values(["freq","total"], ascending=[0,0])

            output_cols = ["cardname","total","freq"]+dates+["moy", "remplis."]
            return result_df.loc[:, output_cols]