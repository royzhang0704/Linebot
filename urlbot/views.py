import requests
from django.core.serializers import serialize
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from linebot.models import TextSendMessage, MessageEvent
from rest_framework.response import Response
from rest_framework  import status
from rest_framework.views import APIView
from linebot import LineBotApi, WebhookParser
from django.conf import settings
from rest_framework import status
from rest_framework.viewsets import ModelViewSet
from .models import Todolist
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from .serializers import TodoListSerializer

class LineBotCallbackAPI(APIView):
    """LINE Bot API 處理類

        此類負責處理所有來自 LINE 的 webhook 請求，並管理各種功能命令。
        支援的功能包括：縮網址、匯率轉換、股票查詢、天氣查詢、新聞搜尋和待辦事項管理。

        Attributes:
            line_bot_api: LINE Bot API 客戶端實例
            parser: LINE Webhook 解析器
            shortener: 網址縮短服務實例
            currency_transform: 匯率轉換服務實例
            weather: 天氣查詢服務實例
            news: 新聞搜尋服務實例
            stock: 股票查詢服務實例
            weather_forecast: 天氣預報服務實例
            todolist: 待辦事項管理實例
            command_handlers: 命令處理器映射字典
    """
    def __init__(self):
        """將每個指令實例化"""
        self.line_bot_api = LineBotApi(settings.LINE_CHANNEL_ACCESS_TOKEN)
        self.parser = WebhookParser(settings.LINE_CHANNEL_SECRET)
        self.shortener = URLShortener()
        self.currency_transform = CurrencyTransformAPI()
        self.news = NewsAPI()
        self.stock = StockAPI()
        self.weather = WeatherIntegratedAPI()
        self.todolist=TodoList()

        #將使用者輸入的指令映射到此
        self.command_handlers = {
            "縮網址": self._handle_url_shortener,
            "匯率": self._handle_currency,
            "股票": self._handle_stock,
            "天氣": self._handle_weather,
            "新聞": self._handle_news,
            "todo": self._handle_todolist
        }
    def get(self,request,*args,**kwargs):
        """測試API是否成功"""
        return Response(
            {
                "success":True,
                "message":"連接成功"
            }
            ,status=status.HTTP_200_OK)
    
    def post(self, request, *args, **kwargs):
        """處理 Line webhook 請求"""

        body = request.body.decode('utf-8') #將使用者輸入用utf-8編碼 避免中文變成亂碼
        signature = request.META.get('HTTP_X_LINE_SIGNATURE', '')

        try:
            events = self.parser.parse(body, signature)
        except InvalidSignatureError:
            return Response({'error': 'Invalid signature'},status=status.HTTP_403_FORBIDDEN)

        except LineBotApiError:
            return Response({'error': 'LineBotApi error'},status=status.HTTP_400_BAD_REQUEST)

        for event in events:
            if isinstance(event, MessageEvent):
                response_text = self._handle_message(event)
                self.line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=response_text)
                )

        return Response({'result': 'ok'}, status=status.HTTP_200_OK)

    def _handle_message(self, event):
        """處理用戶發送的消息

        接收用戶消息並根據命令字分發到對應的處理器進行處理。
        支援的命令格式為：[命令] [參數1] [參數2] ...

        Args:
            event: LINE 消息事件對象，包含用戶發送的消息內容

        Returns:
            str: 處理結果的回覆消息
        """
        #訊息預處理
        user_message = event.message.text.strip()
        input_parts = user_message.split(" ")

        # 尋找對應的指令處理器
        command=next((cmd for cmd in self.command_handlers if user_message.startswith(cmd)),None)

        #找不到指令
        if not command:
            return support_command_message()

        try:
            handler = self.command_handlers[command]
            # todo 指令需要 透過user_id 將資料保存到資料庫
            if command == "todo":
                return handler(input_parts,event.source.user_id)
            return handler(input_parts)
        except Exception as error:
            return error_message(error)

    def _handle_url_shortener(self, input_parts):
        """處理縮網址指令"""
        if len(input_parts) < 2:
            return ("請輸入正確的縮網址格式\n"
                    "   說明: 將長網址轉換為短網址\n"
                    "   格式: 縮網址 [URL]\n"
                    "   範例: 縮網址 https://www.google.com.tw/"
                )

        response = self.shortener.get_shorten_url(input_parts[1])
        return response if isinstance(response, str) else f"對應的縮網址：{response}"

    def _handle_currency(self,input):
        """處理匯率指令"""
        if len(input) < 3:
            return (
            "說明: 查詢即時匯率轉換\n",
            "格式: 匯率 [原幣別] [目標幣別]\n"
            "範例: 匯率 美金 台幣"
            )
        currency1, currency2 = input[1],input[2]
        response = self.currency_transform.get_result(currency1, currency2)
        return response if isinstance(response,str) else f"當前 1 {currency1} 可以兌換 {response} {currency2}"

    def _handle_stock(self,input_part):
        """處理股票指令"""
        if len(input_part) < 2:  # 只輸入指令 沒有股票代碼
            return (
                "說明: 查詢股票即時資訊\n"
                "格式: 股票 [股票代碼]\n"
                "範例: 股票 2330\n"
                )

        if input_part[1] == "外資持股":
            return  self.stock.get_foreign_holdings_info()

        elif input_part[1] == "每日成交":
            return self.stock.get_MI_INDEX20()

        #個股資訊
        else:
            return self.stock.get_stock_full_info(input_part[1])

    def _handle_weather(self, input):
        """處理天氣指令"""
        if len(input) < 2:
            return (
                "請輸入要查詢的縣市名稱\n"
                "範例：天氣 臺北市\n"
                "支援查詢的縣市：\n"
                "北部：臺北市、新北市、基隆市、桃園市、新竹市、新竹縣\n"
                "中部：臺中市、南投縣、彰化縣\n"
                "南部：嘉義市、嘉義縣、臺南市、高雄市、屏東縣\n"
                "東部：宜蘭縣、花蓮縣、臺東縣\n"
                "外島：澎湖縣、金門縣、連江縣"
            )

        location_name = input[1].strip()

        return self.weather.get_weather_info(location_name)

    def _handle_news(self,input):
        """處理新聞指令"""
        if len(input)<2:
            return (
            "說明: 搜尋相關新聞\n"
            "格式: 新聞 [關鍵字]\n"
            "範例: 新聞 財金\n"
            )
        keyword=input[1]
        return self.news.get_new_article(keyword)

    def _handle_todolist(self, input, user_id):
        """處理待辦事項指令"""
        if len(input)<2:
            return (
                "請輸入正確的待辦事項指令\n"
                "支援的指令：\n"
                "todo 列表\n"
                "todo 新增 [事項名稱]\n"
                "todo 刪除 [事項名稱]\n"
                "todo 修改 [事項名稱] [狀態]"
            )

        return self.todolist.handle_command(input, user_id)

class URLShortener:
    """網址縮短服務

        使用 Bitly API 將長網址轉換為短網址的服務類。
        支援 URL 格式驗證和錯誤處理。

        Attributes:
            api_token: Bitly API 認證令牌
            headers: API 請求標頭
            api_url: Bitly API 端點

        使用範例:
            shortener = URLShortener()
            short_url = shortener.get_shorten_url("https://www.example.com")
        """
    def __init__(self):
        """設置API驗證與EndPoint訊息"""
        self.api_token = settings.SHORTEN_URL_API_TOKEN
        self.headers = {'Authorization': f'Bearer {self.api_token}'}
        self.api_url = 'https://api-ssl.bitly.com/v4/shorten'

    def _validate_url(self,url) :
        """驗證Url格式是否正確 避免不必要的API請求"""
        try:
            validator = URLValidator()
            validator(url)
            return True

        except ValidationError:
            return "無效的URL格式 請檢查輸入的網址格式是否正確"

    def _make_request(self, url):
        """處理發送請求 返回一個respose 物件"""
        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json={'long_url': url},
                timeout=5
            )
            response.raise_for_status() #檢查status code
            return response

        except requests.exceptions.Timeout:
            return "請求超時"

        except requests.exceptions.ConnectionError:
            return "網路連接錯誤"

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            error_mapping = {
                400: "無效的請求",
                401: "認證失敗",
                403: "沒有權限",
            }
            return f"代碼錯誤-{status_code}-{error_mapping.get(status_code)}-HTTPError"

    def _handle_response(self, response):
        """處理 API 響應"""
        try:
            data = response.json()
            return data['link']

        except (KeyError, ValueError) as e:
            return f"無效的響應格式: {str(e)}"

    def get_shorten_url(self, long_url: str) -> str:
        """縮短指定的 URL

        Args:
            long_url: 要縮短的原始 URL

        Returns:
            str: 成功時返回縮短後的 URL，失敗時返回錯誤訊息

        Raises:
            Exception: 當發生未預期的錯誤時
        """
        try:
            #驗證URL
            validation_result=self._validate_url(long_url)
            if validation_result is not True:
                return validation_result

            #發送請求
            response = self._make_request(long_url)
            if isinstance(response,str): #如果return 是字串代表報錯
                return response

            #處理響應
            return self._handle_response(response)
        #未知錯誤
        except Exception as e:
            return f"未預期的錯誤: {str(e)}"

class CurrencyTransformAPI:
    """匯率轉換服務

    提供即時匯率轉換功能，支援多種貨幣之間的轉換。
    數據來源：全球即時匯率 API

    支援的貨幣：
        - 美金 (USD)
        - 台幣 (TWD)
        - 日幣 (JPY)
        - 人民幣 (CNY)
        - 越南盾 (VND)
        - 英鎊 (GBP)
        - 韓元 (KRW)

    使用範例:
        api = CurrencyTransformAPI()
        rate = api.get_result("美金", "台幣")
    """
    def __init__(self):
        """初始EndPoint與貨幣語言轉換"""
        self.url='https://tw.rter.info/capi.php'
        self.text = {
        '美金': 'USD',
        '台幣': 'TWD',
        '日幣': 'JPY',
        '人民幣': 'CNY',
        '越南盾': 'VND',
        '英鎊': 'GBP',
        '韓元': 'KRW',
    }
        self.support_text="美金,台幣,日幣,人民幣,越南盾,英鎊,韓元" #未來更好擴充 不要用硬編碼
    def _validate_input(self,input_currency1,input_currency2):
        """驗整輸入在支援內"""
        if input_currency1 not in self.text or input_currency2 not in self.text:
            return f"當前支援的貨幣有{self.support_text}"

        return True

    def _make_request(self):
        """返回一個requests.Response 物件"""
        try:
            responses = requests.get(self.url,timeout=5)
            return responses

        except requests.exceptions.ConnectionError:
            return  ("網路出現錯誤")

        except requests.exceptions.Timeout:
            return ("請求超時")

        except requests.exceptions.HTTPError as e:
            status_code=e.response.status_code
            error_mapping={
                400:'無效請求',
                401:'認證失敗',
                403:'沒有權限'
            }
            return f"代碼錯誤-{status_code}-{error_mapping.get(status_code)}-{e}"

    def _handle_response(self,response,currency1,currency2):
        try:
            data=response.json()
            usd_to_currency1_rate = float(data.get(f"USD{self.text[currency1]}")['Exrate'])
            usd_to_currency2_rate = float(data.get(f"USD{self.text[currency2]}")['Exrate'])
            return round(usd_to_currency2_rate / usd_to_currency1_rate, 4)

        except (KeyError,ValueError) as e:
            return  (f"無效響應格式{str(e)}")

    def get_result(self,currency1,currency2):
        try:
            #檢查使用者輸入
            validate_result=self._validate_input(currency1,currency2)
            if validate_result is not True:
                return  validate_result

            #驗證請求
            response=self._make_request()
            if isinstance(response,str):
                return response

            #處理響應
            return self._handle_response(response,currency1,currency2)

        #未知錯誤
        except Exception as e:
            return  f"未預期錯誤{str(e)}"

class WeatherAPI:
    """
    中央氣象署即時天氣觀測服務

        提供台灣各地即時天氣觀測資料的查詢服務。
        數據來源：中央氣象署開放資料平臺之資料擷取API

        功能特點：
            - 即時天氣狀況查詢
            - 各氣象站觀測數據
            - 自動處理 API 請求錯誤
            - 支援多個觀測點資料

        資料內容：
            - 觀測站基本資訊
            - 即時天氣狀況
            - 溫度資訊（目前溫度、最高溫、最低溫）
            - 降雨量數據
            - 紫外線指數

        使用範例：
            weather_api = WeatherAPI()
            current_weather = weather_api.get_current_weather("臺北")
        """
    def __init__(self):
        self.url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0003-001" #現在天氣觀測報告
        self.params = {'Authorization': settings.WEATHER_API_TOKEN}

    def _make_request(self):
        try:
            response = requests.get(self.url, params=self.params, timeout=5)
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            return "請求超時"

        except requests.exceptions.HTTPError as e:
            return f"請求錯誤{str(e)}"

    def _handle_response(self,response):
        """return Json資料"""
        if isinstance(response, str):
            return response

        try:
            data = response.json()
            return data

        except Exception as e:
            return f"解析資料錯誤{str(e)}"

    def get_current_weather(self,location_name):
        """ 驗證request與response 是否正確 再return user對應要找的資料"""
        response = self._make_request()
        if isinstance(response, str): #Request報錯
            return response
        try:
            data = self._handle_response(response)

            if isinstance(data,str): #Response報錯
                return data

            response_data=""    #init

            data=data.get('records', {}).get('Station', [])
            for item in data:
                if item.get('StationName')==location_name:
                    daily_extreme=item.get('WeatherElement').get('DailyExtreme')   #拿取當天溫度最高最低data
                    response_data=(
                        f"氣象站名稱:{item.get('StationName','N/A')}\n"
                        f"觀測時間:{item.get('ObsTime').get('DateTime','N/A')}\n"
                        f"天氣:{item.get('WeatherElement').get('Weather','N/A')}\n"
                        f"目前降雨量:{item.get('WeatherElement').get('Now').get('Precipitation','N/A')}毫米\n"
                        f"紫外線指數:{item.get('WeatherElement').get('UVIndex','N/A')}\n"
                        f"氣溫:{item.get('WeatherElement').get('AirTemperature','N/A')}\n"
                        f"當日最高溫:{daily_extreme.get('DailyHigh').get('TemperatureInfo').get('AirTemperature')}度\n"
                        f"當日最低溫:{daily_extreme.get('DailyLow').get('TemperatureInfo').get('AirTemperature')}度\n"
                    )
            return response_data if response_data else f"找不到{location_name}的觀測站資料"

        except Exception as e:
            return f"非預期錯誤{str(e)}"

class WeatherForecastAPI:
    """天氣預報服務

    提供 36 小時內的天氣預報資訊。
    數據來源：中央氣象署開放資料平臺。

    提供的天氣資訊：
        - 天氣狀況
        - 降雨機率
        - 溫度範圍
        - 舒適度

    時段劃分：
        - 今天白天
        - 今晚明晨
        - 明天白天

    使用範例:
        weather = WeatherForecastAPI()
        forecast = weather.get_weather_forecast("臺北市")
    """

    def __init__(self):
        self.url = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"
        self.params = {'Authorization': settings.WEATHER_API_TOKEN}

    def _make_request(self):
        """發送請求"""
        try:
            response = requests.get(self.url, params=self.params, timeout=5)
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            return "請求超時"

        except requests.exceptions.HTTPError as e:
            return f"請求錯誤: {str(e)}"

    def _get_weather_period_text(self, time_idx):
        """將時間區段轉換為易讀文字"""
        periods = ["今天白天", "今晚明晨", "明天白天"]
        return periods[time_idx]

    def _handle_response(self,response,location_name):
        """處理 API 回應資料"""
        if isinstance(response, str):
            return response

        try:
            data = response.json()
            locations = data.get('records', {}).get('location', [])

            # 如果指定地區，只返回該地區資料
            if location_name:
                locations = [loc for loc in locations if loc['locationName'] == location_name]
                if not locations:
                    return f"找不到 {location_name} 的天氣預報"

            weather_info = []
            for location in locations:
                location_name = location['locationName']
                weather_elements = location['weatherElement']

                # 建立易於存取的天氣要素字典
                elements_dict = {elem['elementName']: elem['time'] for elem in weather_elements}

                location_text = f"{location_name}天氣預報\n"

                #處理每個時間區段
                for time_idx in range(3):
                    period_text = self._get_weather_period_text(time_idx)
                    location_text += f"\n{period_text}（{elements_dict['Wx'][time_idx]['startTime'][11:16]}-{elements_dict['Wx'][time_idx]['endTime'][11:16]}）：\n"

                    # 天氣現象
                    wx = elements_dict['Wx'][time_idx]['parameter']['parameterName']
                    location_text += f"天氣狀況：{wx}\n"

                    # 降雨機率
                    pop = elements_dict['PoP'][time_idx]['parameter']['parameterName']
                    location_text += f"降雨機率：{pop}%\n"

                    # 溫度範圍
                    min_t = elements_dict['MinT'][time_idx]['parameter']['parameterName']
                    max_t = elements_dict['MaxT'][time_idx]['parameter']['parameterName']
                    location_text += f"溫度範圍：{min_t}°C - {max_t}°C\n"

                    # 舒適度
                    ci = elements_dict['CI'][time_idx]['parameter']['parameterName']
                    location_text += f"舒適度：{ci}\n"

                weather_info.append(location_text)

            return "\n".join(weather_info)

        except Exception as e:
            return f"解析資料錯誤: {str(e)}"

    def get_weather_forecast(self, location_name):
        """獲取天氣預報資訊"""
        if not location_name:
            return "請輸入要查詢的縣市地點"
        response = self._make_request()
        if isinstance(response, str):
            return response

        try:
            return self._handle_response(response,location_name)
        except Exception as e:
            return f"非預期錯誤: {str(e)}"

class StockAPI:
    """股票資訊查詢服務

       提供台灣股市相關資訊查詢功能。
       數據來源：臺灣證券交易所 OpenAPI

       支援功能：
           - 外資持股前五名統計
           - 每日成交量前五名
           - 個股完整資訊查詢

       提供的資訊：
           - 基本報價資訊（股價、漲跌幅）
           - 技術指標（本益比、股價淨值比）
           - 交易統計（成交量、成交金額）

       使用範例:
           api = StockAPI()
           stock_info = api.get_stock_full_info("2330")
       """
    def __init__(self):
        self.url_fund_MI_QFIIS_sort_20 = "https://openapi.twse.com.tw/v1/fund/MI_QFIIS_sort_20"  # 集中市場外資及陸資持股前5名統計表
        self.url_MI_INDEX20="https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX20" #集中市場每日成交量前5名證券
        self.url_BWIBBU_ALL="https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL" #個股基本資料(含收盤價、本益比、股價淨值比)
        self.url_STOCK_DAY_ALL= "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"# 個股日成交資訊

    def _make_request(self,url):
        """檢查request請求"""
        try:
            response=requests.get(url,timeout=5)
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            return "請求超時"

        except requests.exceptions.RequestException as e:
            return f"請求錯誤:{str(e)}"

    def _handle_response(self,response):
        """檢查解析資料回傳給client"""

        if isinstance(response,str): #request報錯
            return response

        try:
            return response.json()
        except Exception as e: #response報錯
            return f"解析資料錯誤:{str(e)}"

    def get_foreign_holdings_info(self):
        """獲取外資持股前5名資訊"""
        response=self._make_request(self.url_fund_MI_QFIIS_sort_20)
        data=self._handle_response(response)
        text="當前外資持股前五名為\n"

        if isinstance(data,str):
            return data

        for i in data[:5]:
            text+=(
            f"名次: {i.get('Rank')}\n"
            f"股票: {i.get('Name')}\n"
            f"代號為: {i.get('Code')}\n"
            f"總股數為: {int(i.get('ShareNumber'))}\n"
            f"可投資股數: {int(i['AvailableShare']):,}股\n"
            f"已投資股數: {int(i['SharesHeld']):,}股\n"
            f"可投資比例: {i['AvailableInvestPer']}%\n"
            f"已投資比例: {i['SharesHeldPer']}%\n"
            f"上限比例: {i['Upperlimit']}%\n"
            f"---------------------------\n"
            )
        return text

    def get_MI_INDEX20(self):
        """集中市場每日成交量前五名證券"""
        response=self._make_request(self.url_MI_INDEX20)
        data=self._handle_response(response)

        if isinstance(data,str):
            return response

        try:
            text="集中市場每日成交量前五名證券\n"
            for i in data[:5]:
                text += (
                    f"名次: {i['Rank']}\n"
                    f"股票: {i['Name']}({i['Code']})\n"
                    f"成交量: {int(i['TradeVolume']):,}張\n"
                    f"成交筆數: {int(i['Transaction']):,}筆\n"
                    f"收盤價: {i['ClosingPrice']}\n"
                    f"漲跌: {i['Dir']}{i['Change']}\n"
                    f"最高: {i['HighestPrice']} / 最低: {i['LowestPrice']}\n"
                    "-------------------------------\n"
                )
            return text

        except Exception as e:
            return f"資料處理錯誤: {str(e)}"

    def get_stock_full_info(self, stock_code):
        """獲取完整的股票資訊"""
        # 取得基本資料
        basic_response = self._make_request(self.url_BWIBBU_ALL)
        basic_data = self._handle_response(basic_response)

        # 取得交易資料
        daily_response = self._make_request(self.url_STOCK_DAY_ALL)
        daily_data = self._handle_response(daily_response)

        if isinstance(basic_data, str) or isinstance(daily_data, str):
            return "資料獲取失敗\n"

        try:
            #處理基本訊息
            basic_info = None
            for item in basic_data:
                if item['Code'] == stock_code:
                    basic_info = item
                    break

            # 處理交易資料
            daily_info = None
            for item in daily_data:
                if item['Code'] == stock_code:
                    daily_info = item
                    break

            if not basic_info or not daily_info:
                return f"找不到股票代碼 {stock_code} 的資訊"

            return (
                f"{basic_info['Name']}({stock_code}) 股票資訊\n"
                f"\n價格資訊\n"
                f"收盤價: {daily_info['ClosingPrice']}元\n"
                f"漲跌: {daily_info['Change']}元\n"
                f"最高/最低: {daily_info['HighestPrice']}/{daily_info['LowestPrice']}\n"
                f"\n技術指標\n"
                f"本益比: {basic_info['PEratio']}\n"
                f"股價淨值比: {basic_info['PBratio']}\n"
                f"殖利率: {basic_info['DividendYield']}%\n"
                f"交易量\n"
                f"成交量: {int(daily_info['TradeVolume']):,}股\n"
                f"成交金額: {int(daily_info['TradeValue']):,}元\n"
                )

        except Exception as e:
            return f"資料處理錯誤: {str(e)}"

class NewsAPI:
    """
    新聞搜尋服務

        提供新聞文章搜尋功能。
        數據來源：News API

        回傳資訊：
            - 新聞來源
            - 作者
            - 標題
            - 文章連結
            - 圖片連結
            - 發布日期

        特點：
            - 支援中文搜尋
            - 每次返回最新的三則新聞
            - 自動處理缺失資訊

        使用範例:
            api = NewsAPI()
            news = api.get_new_article("科技")
        """
    def __init__(self):
        self.url='https://newsapi.org/v2/everything'
        self.api_key=settings.GET_NEWS_API_TOKEN

    def _make_request(self,query)-> requests.Response:
        """ 返回一個response物件"""
        try:
            # 查詢參數
            self.params = {
                'q': query,
                'language': 'zh',
                'apiKey': self.api_key
            }
            response=requests.get(self.url,params=self.params,timeout=5)
            response.raise_for_status()
            return response

        except requests.exceptions.Timeout:
            return "請求超時"

        except requests.RequestException as e:
            return f"請求錯誤{str(e)}"

    def _handle_response(self,response):
        """處理資料格式"""
        if isinstance(response,str):
            return response
        try:
            article_list = response.json().get('articles', [])
            if not article_list:
                return "找不到相關的內文 請重新嘗試新的關鍵字"

            result_data = []
            for data in article_list[:3]: #取前三則新聞
                source = data['source'].get('name','未知來源')
                author = data.get('author', '未知作者')
                title = data.get('title', '未知標題')
                url = data.get('url', '未知網址')
                image = data.get('urlToImage', '未知圖片')
                date = data.get('publishedAt', '未知日期')

                news_item = (
                    f"來源名稱:{source}\n"
                    f"作者:{author}\n"
                    f"標題:{title}\n"
                    f"文章網址:{url}\n"
                    f"文章圖片:{image}\n"
                    f"發布日期:{date}\n"
                    "--------------------------------------------------------"
                )
                result_data.append(news_item)
            return "\n".join(result_data)

        except Exception as e:
            return f"資料錯誤 {str(e)}"

    def get_new_article(self,keyword):
        """給外部call 主funtion 負責檢查request跟response是否有錯誤"""
        response=self._make_request(keyword)
        data=self._handle_response(response)

        if isinstance(data,str):
            return data
        try:
            return data

        except Exception as e: #未預期錯誤
            return f"發生錯誤 {str(e)}"

class TodoList:
    """待辦事項管理系統

    提供基本的待辦事項 CRUD（創建、讀取、更新、刪除）功能。
    支援多用戶管理，每個用戶擁有獨立的待辦清單。

    功能：
        - 新增待辦事項
        - 刪除待辦事項
        - 更新待辦事項狀態
        - 查看待辦清單

    待辦事項狀態：
        - completed: 已完成
        - pending: 待處理

    使用範例:
        todo = TodoList()
        todo.create_todo(["todo", "新增", "運動"], "user123")
        todo.retrieve_todo(["todo", "列表"], "user123")
    """

    def __init__(self):
        self.commands = {
            "新增": self.create_todo,
            "刪除": self.delete_todo,
            "修改": self.update_todo,
            "列表": self.retrieve_todo
        }

    def handle_command(self, input_parts, user_id) -> str:
        """處理待辦事項指令"""

        command = input_parts[1]

        if (command!="列表" and len(input_parts)<3) or command not in self.commands:
            return   (
                "說明: 待辦事項管理\n"
                "子指令\n"
                "列表: 查看所有待辦事項\n"
                "新增: 新增待辦事項 (todo 新增 [事項名稱])\n"
                "刪除: 刪除待辦事項 (todo 刪除 [事項名稱])\n"
                "修改: 更改待辦狀態 (todo 修改 [事項名稱] completed/pending)\n"
                )
        handler = self.commands[command]
        return handler(input_parts, user_id)

    def create_todo(self,input,user_id):
        """新增待辦事項"""
        data={
            'title':input[2],
            'user_id':user_id
        }

        serializer=TodoListSerializer(data=data)
        todo=Todolist.objects.filter(user_id=user_id,title=input[2]).first()
        if todo:
            return f"{todo.title}已存在 無法重複新增"

        if serializer.is_valid():
            todo=serializer.save()
            return f"成功新增{todo.title}"

        return "新增失敗"

    def delete_todo(self,input,user_id):
        """刪除todo物件"""

        #一次刪除全部
        if input[2]=="全部":
            todo=Todolist.objects.filter(user_id=user_id)

            if todo:
                todo.delete()
                return f"代辦事項已全部刪除"

            return "當前代辦事項已經為空 不需要刪除!"

        todo = Todolist.objects.filter(user_id=user_id, title=input[2]).first()

        if not todo:
            return "當前事項不存在"

        todo.delete()
        response_text = f"成功刪除{todo.title}"
        return response_text

    def update_todo(self,input,user_id):
        """更新代辦事項的狀態"""
        if len(input)<4:
            return "請輸入要修改的狀態 請使用completed 或是 pending"

        todo = Todolist.objects.filter(user_id=user_id, title=input[2]).first()

        if not todo:
            return "找不到該待辦事項"

        title = input[2]
        new_status = input[3]
        if new_status not in ['completed','pending']:
            return "無效的狀態修改,請使用 completed 或是 pending"

        if todo.status==new_status:
            return f"{title}已是{new_status}狀態了"

        todo.status = new_status
        todo.save()
        serializer = TodoListSerializer(todo)
        response_text = f"已成功把{serializer.data['title']}修改為 {serializer.data['status']}狀態了!"

        return response_text

    def retrieve_todo(self,input,user_id):
        """查看使用者已儲存的代辦事項"""

        todos = Todolist.objects.filter(user_id=user_id)
        serializer = TodoListSerializer(todos, many=True)

        if not serializer.data:
            return "目前沒有待辦事項"

        response_text = "您的待辦清單如下\n"

        for i, todo in enumerate(serializer.data, 1):
            status = "✅" if todo['status'] == "completed" else "⭕"
            response_text += f"{i}. {status} {todo['title']}\n"

        return response_text

class WeatherIntegratedAPI:
    """整合天氣查詢服務"""

    def __init__(self):
        self.current_weather_api = WeatherAPI()
        self.forecast_api = WeatherForecastAPI()
        # 縣市對應到觀測站名稱的對照表
        self.station_mapping = {
            # 北部
            "臺北市": "臺北",
            "新北市": "板橋",
            "基隆市": "基隆",
            "桃園市": "新屋",
            "新竹市": "新竹",
            "新竹縣": "新竹",
            # 中部
            "臺中市": "臺中",
            "南投縣": "日月潭",
            "彰化縣": "彰師大",
            # 南部
            "嘉義市": "嘉義",
            "嘉義縣": "阿里山",
            "臺南市": "臺南",
            "高雄市": "高雄",
            "屏東縣": "恆春",
            # 東部
            "宜蘭縣": "宜蘭",
            "花蓮縣": "花蓮",
            "臺東縣": "臺東",
            # 外島
            "澎湖縣": "澎湖",
            "金門縣": "金門",
            "連江縣": "馬祖",
        }

    def get_weather_info(self, location_name: str) -> str:
        """獲取整合的天氣資訊

        Args:
            location_name: 縣市名稱 (例如：臺北市、嘉義縣)

        Returns:
            str: 整合的天氣資訊
        """
        if not location_name:
            return "請輸入要查詢的縣市名稱\n範例：天氣 臺北市"

        # 先取得天氣預報（以縣市名稱查詢）
        forecast = self.forecast_api.get_weather_forecast(location_name)

        # 找到對應的觀測站名稱
        station_name = self.station_mapping.get(location_name)
        current_weather = None
        if station_name:
            current_weather = self.current_weather_api.get_current_weather(station_name)

        # 組合輸出訊息
        message = f"🌈 {location_name} 天氣資訊\n"
        message += "=" * 30 + "\n\n"

        if "找不到" in forecast:
            return (
                f"❌ 找不到 {location_name} 的天氣資訊\n"
                "請輸入完整的縣市名稱，例如：\n"
                "- 臺北市（而不是 臺北）\n"
                "- 嘉義市 或 嘉義縣\n"
                "支援查詢的縣市：\n"
                "北部：臺北市、新北市、基隆市、桃園市、新竹市、新竹縣\n"
                "中部：臺中市、南投縣、彰化縣\n"
                "南部：嘉義市、嘉義縣、臺南市、高雄市、屏東縣\n"
                "東部：宜蘭縣、花蓮縣、臺東縣\n"
                "外島：澎湖縣、金門縣、連江縣"
            )

        # 優先顯示預報資訊
        if forecast and "找不到" not in forecast:
            message += "🔮 天氣預報\n"
            message += forecast + "\n"

        # 如果有觀測站資料，則顯示即時觀測
        if current_weather and "找不到" not in current_weather:
            message += "\n📍 即時觀測"
            if station_name != location_name:
                message += f"（{station_name}觀測站）"
            message += "\n"
            message += current_weather

        return message

def support_command_message():
    """顯示所有支援的指令說明

    整理並展示所有可用的指令格式與使用範例，協助用戶正確使用服務。

    Returns:
        str: 格式化的指令說明文字

    使用範例:
        當用戶輸入未知指令時顯示此訊息
    """
    commands = {
        "縮網址": {
            "說明": "將長網址轉換為短網址",
            "格式": "縮網址 [URL]",
            "範例": "縮網址 https://www.google.com.tw/",
        },
        "匯率": {
            "說明": "查詢即時匯率轉換",
            "格式": "匯率 [原幣別] [目標幣別]",
            "範例": "匯率 美金 台幣",
        },
        "股票": {
            "說明": "查詢股票即時資訊",
            "格式": "股票 [股票代碼]",
            "範例": "股票 2330",
        },
        "天氣": {
            "說明": "查詢36小時天氣預報",
            "格式": "天氣 [縣市名]",
            "範例": "天氣 嘉義",
        },
        "新聞": {
            "說明": "搜尋相關新聞",
            "格式": "新聞 [關鍵字]",
            "範例": "新聞 財金",
        },
        "todo": {
            "說明": "待辦事項管理",
            "子指令": {
                "列表": "查看所有待辦事項",
                "新增": "新增待辦事項 (todo 新增 [事項名稱])",
                "刪除": "刪除待辦事項 (todo 刪除 [事項名稱])",
                "修改": "更改待辦狀態 (todo 修改 [事項名稱] completed/pending)",
            },
            "範例": [
                "todo 列表",
                "todo 新增 運動",
                "todo 刪除 運動",
                "todo 修改 運動 completed",
            ],
        },
    }

    # 組織輸出格式
    message = "📝 指令使用說明\n" + "=" * 30 + "\n\n"

    for cmd, info in commands.items():
        message += f"🔸 {cmd}\n"
        message += f"  說明：{info['說明']}\n"

        if "格式" in info:
            message += f"  格式：{info['格式']}\n"

        if "子指令" in info:
            message += "  子指令：\n"
            for subcmd, desc in info['子指令'].items():
                message += f"    - {subcmd}: {desc}\n"

        message += "  範例：\n"
        if isinstance(info.get('範例'), list):
            for example in info['範例']:
                message += f"    {example}\n"
        else:
            message += f"    {info['範例']}\n"

        message += "\n"

    return message

def error_message(message):
    """格式化錯誤訊息

    將系統錯誤訊息轉換為用戶友善的格式。

    Args:
        message: 原始錯誤訊息

    Returns:
        str: 格式化後的錯誤訊息

    使用範例:
        error_message("API連線失敗")
    """
    error_template = (
            "❌ 發生錯誤\n"
            "=" * 20 + "\n"
            f"錯誤描述: {message}\n"
            "請稍後再試。\n"
            "=" * 20
    )
    return error_template