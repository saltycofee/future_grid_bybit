import ast
import ctypes
import hashlib
import hmac
import inspect
import json
import ssl
import threading
import time
import tkinter as tk
from tkinter import ttk

import logger
import requests
import urllib3
import websocket
from tksheet import Sheet

history_list=[]
history_list_len = 0
datalist = [] #
orderlist = [] # order topic 返回的数据
first_buy_price = 0.00 #第一档的买价
first_sell_price = 0.00 #第一档的卖盘价
start_time=time.time()

# order_list = []
# private_thread_status = 0  # 0存活 ，1 死亡
# public_thread_status =0 # 0存活 ，1 死亡
private_thread = threading.Thread()
public_thread = threading.Thread()
grid_thread = threading.Thread()

notice_message =''

inint_monitor_list = []
log_file_name = time.strftime('%Y-%m-%d', time.localtime(time.time())) +'future_grid.log'
log = logger.Logger(log_file_name, level='info')

class Trading_srv():
    def __init__(self,apikey,secret_key,symbol, money, gridnum,side, bttomprice, topprice, leverage, symbol_min_qty, UnPL):
        super(Trading_srv, self).__init__()
        self.host= 'https://api.bybit.com' #主网接口地址
        # self.host = 'https://api-testnet.bybit.com'  # 测试环境
        self.ws=None
        # self.wshost = host  #订阅地址host
        self.api_key = apikey
        self.secret_key = secret_key
        self.screatkey = bytes(secret_key,encoding="utf8")
        self.symbol=symbol
        self.money=money
        self.gridnum=gridnum
        self.side=side
        self.bttomprice=bttomprice
        self.topprice=topprice
        self.leverage=leverage
        self.symbol_min_qty=symbol_min_qty
        self.UnPL=UnPL


    def Post(self,url, params, sign_real):
        '''
        Post 方法
        :return:
        '''
        url = self.host + url
        headers = {"Content-Type": "application/json"}
        body = dict(params, **sign_real)
        urllib3.disable_warnings()
        s = requests.session()
        s.keep_alive = False
        flag = 1
        while flag:
            try:
                response = requests.post(url, data=json.dumps(body), headers=headers, verify=False)
                print(response.text)
                return response.text
            except Exception as e:
                print(e)

    # 签名认证
    def CreateSign(self,params, secretKey):
        sign = ''
        for key in sorted(params.keys()):
            v = params[key]
            if isinstance(params[key], bool):
                if params[key]:
                    v = 'true'
                else:
                    v = 'false'
            sign += key + '=' + str(v) + '&'
        sign = sign[:-1]
        # print(sign)
        hash = hmac.new(secretKey, sign.encode("utf-8"), hashlib.sha256)
        signature = hash.hexdigest()
        sign_real = {
            "sign": signature
        }
        return sign_real

    # 创建活动订单
    def createorder(self,params, sign_real):
        '''
        创建活动订单
        :param params:
        :param sign_real:
        :return:
        '''
        url = "/private/linear/order/create"
        response = self.Post(url, params, sign_real)
        res = json.loads(response)
        if res["ret_code"] == 0 and res['ret_msg'] == "OK":
            return res
        else:
            return "下单失败!"

    # 初始化需要监控的表格
    def Init_Monitor_Order(self,symbol, money, gridnum, side, bttomprice, topprice, leverage, symbol_min_qty, UnPL):
        '''
        初始化需要监控的表格
        :param symbol: btc,usdt
        :param money: usdt
        :param gridnum: invensent money
        :param side: deriction
        :return:
        '''
        global first_sell_price
        global first_buy_price
        global inint_monitor_list
        money = float(money)
        gridnum = int(gridnum)
        bttomprice = float(bttomprice)
        topprice = float(topprice)
        leverage = float(leverage)
        symbol_min_qty = float(symbol_min_qty)
        UnPL = float(UnPL)

        if side == 'long':  # 做多
            if (money / gridnum * leverage) / topprice > symbol_min_qty:
                qty = float('%.3f' % ((money / gridnum * leverage) / topprice))
                if symbol == "BTCUSDT":  # ticksize
                    step_price = '%.1f' % float((topprice - bttomprice) / (gridnum - 1))
                    print("========》每个格子间隔的距离", step_price)
                    log.logger.info("========》每个格子间隔的距离" + str(step_price))
                    ticksize = 0.5
                    if int(step_price.split(".")[1]) > 5:
                        step_price = ".".join((step_price.split(".")[0], str(5)))
                    else:
                        step_price = ".".join((step_price.split(".")[0], str(0)))
                    for i in range(1, gridnum):
                        buy_price = bttomprice + i * float(step_price)
                        every_grid_size = float((money / gridnum * leverage) / topprice)
                        every_grid_money = float(money / gridnum)
                        # 根据盈利百分比计算sell价格
                        sell_price = "%.1f" % float((UnPL * (
                                (every_grid_size * buy_price / leverage) + (every_grid_size * buy_price * 0.00075) + (
                                every_grid_size * buy_price * (
                                (leverage - 1) / leverage) * 0.00075)) / every_grid_size) + buy_price)
                        if int(sell_price.split(".")[1]) > 5:
                            sell_price = ".".join((sell_price.split(".")[0], str(5)))
                        else:
                            sell_price = ".".join((sell_price.split(".")[0], str(0)))
                        inint_monitor_list.append({
                            'buy_price': float(buy_price),
                            'buy_price_status': 0,
                            'buy_price_order_id': '',
                            'buy_qty': qty,
                            'symbol': symbol,
                            'sell_price': float(sell_price),
                            'sell_price_status': 0,
                            'sell_price_order_id': '',
                            'sell_qty': qty,
                        })
                else:
                    pass

                # 开始初始化下单
                for index, preline in enumerate(inint_monitor_list):
                    if preline['buy_price'] < first_buy_price:
                        createbuyorder_Params = {
                            "side": "Buy",
                            "symbol": preline['symbol'],
                            "order_type": "Limit",
                            "qty": qty,
                            "price": preline['buy_price'],
                            "close_on_trigger": False,
                            "time_in_force": "PostOnly",
                            "api_key": self.api_key,
                            "timestamp": "1542782900000",
                            "recv_window": "93800000000",
                            "reduce_only": False,
                        }
                        signdic = self.CreateSign(createbuyorder_Params, self.screatkey)
                        try:
                            createbuy_Res = self.createorder(createbuyorder_Params, signdic)
                            buyorder_id = createbuy_Res['result']['order_id']
                            print("下买单成功==>", buyorder_id)
                            log.logger.info("下买单成功==>" + str(buyorder_id))
                            # update monitordic
                            inint_monitor_list[index]['buy_price_order_id'] = buyorder_id
                            inint_monitor_list[index]['buy_price_status'] = 1
                            inint_monitor_list[index]['buy_qty'] = qty
                        except Exception as e:
                            print(e, "网络波动下单失败!")
                            log.logger.info(str(e) + "网络波动下单失败!")
                        # 更新
                    else:
                        print("价格高于市价，不挂单")
                        log.logger.info("价格高于市价，不挂单")
                        pass
            else:
                print("下单量小于最小额度，请减少网格数量或增加投入本金")
                log.logger.info("下单量小于最小额度，请减少网格数量或增加投入本金")

        elif side == 'short':  # 做空
            print('做空方向')
        else:
            print("没有该方向!")
            log.logger.info("没有该方向!")

    # 维护订单状态
    def update_topic_orderlist(self,datalist):
        '''
        维护orderlist的信息
        :return:
        '''
        global orderlist
        for data in datalist:
            orderlist.append({'order_id': data["order_id"],
                              'symbol': data['symbol'],
                              'side': data['side'],
                              'price': data['price'],
                              'qty': data['qty'],
                              'order_status': data['order_status'],
                              'update_time': data['update_time'],
                              'money': "%.2f" % (float(data['price']) * float(data['qty'])),
                              })

    # 更新inint_monitor_list 的数据
    def update_inint_monitor_list(self):
        '''
        更新监控list的数据
        :return:
        '''
        global inint_monitor_list
        global orderlist
        global history_list
        for index, value in enumerate(inint_monitor_list):
            for li in orderlist:
                if value['buy_price_order_id'] == li['order_id']:
                    if li['order_status'] == 'New' or li['order_status'] == 'PartiallyFilled':
                        # 订单未被成交完成,不管
                        pass
                    elif li['order_status'] == 'Filled':
                        # 订单已经成交或被取消，需要更新monitor
                        inint_monitor_list[index]['buy_price_status'] = 0  #
                        inint_monitor_list[index]['buy_price_order_id'] = ''
                        # 挂卖单
                        createbuyorder_Params = {
                            "side": "Sell",
                            "symbol": value['symbol'],
                            "order_type": "Limit",
                            "price": value['sell_price'],
                            "qty": value['buy_qty'],
                            "close_on_trigger": False,
                            "time_in_force": "PostOnly",
                            "api_key": self.api_key,
                            "timestamp": "1542782900000",
                            "recv_window": "93800000000",
                            "reduce_only": True,
                        }
                        createbuy_Res = self.createorder(createbuyorder_Params, self.CreateSign(createbuyorder_Params, self.screatkey))
                        sellorder_id = createbuy_Res['result']['order_id']
                        print("下卖单成功==>", sellorder_id)
                        log.logger.info("下卖单成功==>" + str(sellorder_id))
                        # update monitordic
                        inint_monitor_list[index]['sell_price_order_id'] = sellorder_id
                        inint_monitor_list[index]['sell_price_status'] = 1
                        inint_monitor_list[index]['sell_qty'] = value['buy_qty']
                    elif li['order_status'] == 'Cancelled':
                        # 订单已经被取消 需要重新挂单
                        print("订单被取消，请查看问题")
                        log.logger.info("订单被取消，请查看问题")

                    else:
                        print("《======买单存在异议========》")
                        log.logger.info("《======买单存在异议========》")
                if value['sell_price_order_id'] == li['order_id']:  # 卖出订单的状态
                    if li['order_status'] == 'New' or li['order_status'] == 'PartiallyFilled':
                        # 订单未被成交,不管
                        pass
                    elif li['order_status'] == 'Filled':
                        # 订单已经成交或被取消，需要更新monitor
                        inint_monitor_list[index]['sell_price_status'] = 0  # 成交
                        inint_monitor_list[index]['sell_price_order_id'] = ''
                        # 卖单已成交，需要放到列表里面
                        time = li['update_time'].replace("T", " ").split(".")[0]
                        end_money = li['money']
                        start_money = "%.2f" % (float(value['buy_price']) * float(value['buy_qty']))
                        profit_money = float(end_money) - float(start_money)
                        profit_rate = str(profit_money / float(start_money) * 100) + "%"
                        orderlisting = [li['symbol'], time, li['money'], profit_money, "USDT", profit_rate]
                        history_list.append(orderlisting)
                        # 卖单已成交，需要挂买单
                        createbuyorder_Params = {
                            "side": "Buy",
                            "symbol": value['symbol'],
                            "order_type": "Limit",
                            "qty": value['sell_qty'],
                            "price": value['buy_price'],
                            "close_on_trigger": False,
                            "time_in_force": "PostOnly",
                            "api_key": self.api_key,
                            "timestamp": "1542782900000",
                            "recv_window": "93800000000",
                            "reduce_only": False,
                        }
                        signdic = self.CreateSign(createbuyorder_Params, self.screatkey)
                        try:
                            createbuy_Res = self.createorder(createbuyorder_Params, signdic)
                            buyorder_id = createbuy_Res['result']['order_id']
                            print("下买单成功==>", buyorder_id)
                            log.logger.info("下买单成功==>" + str(buyorder_id))
                            # update monitordic
                            inint_monitor_list[index]['buy_price_order_id'] = buyorder_id
                            inint_monitor_list[index]['buy_price_status'] = 1
                            inint_monitor_list[index]['buy_qty'] = value['sell_qty']
                        except Exception as e:
                            print(e, "网络波动下单失败!")
                            log.logger.info(str(e) + "网络波动下单失败!")

                    elif li['order_status'] == 'Cancelled':
                        print("单子被取消，请查看问题")
                        log.logger.info("单子被取消，请查看问题")
                    else:
                        print("《======卖单存在异议========》")
                        log.logger.info("《======卖单存在异议========》")

    # 循环监控订单状态
    def Monitor(self):
        '''
        监控
        :return:
        '''
        global inint_monitor_list
        global first_buy_price
        # 先更新 inint_monitor_list
        self.update_inint_monitor_list()
        print("<+++++++++++++++++++>追加的订单列表信息", orderlist)
        log.logger.info("<+++++++++++++++++++>追加的订单列表信息" + str(orderlist))
        print("<=================>监控的订单列表信息", inint_monitor_list)
        log.logger.info("<=================>监控的订单列表信息" + str(inint_monitor_list))
        for index, value in enumerate(inint_monitor_list):
            if value['buy_price_status'] == 0 and value['sell_price_status'] == 0:
                # 买单和卖单均没有挂,挂买单
                # print("买单和卖单均没有挂,挂买单")
                pass
                # 要和市价进行比对，若低于市价则不挂
                if inint_monitor_list[index]['buy_price'] > first_buy_price:
                    # print("高于市价===》不挂单")
                    pass
                else:
                    paramas = {
                        "side": "Buy",
                        "symbol": inint_monitor_list[index]['symbol'],
                        "order_type": "Limit",
                        "qty": inint_monitor_list[index]['buy_qty'],
                        "price": inint_monitor_list[index]['buy_price'],
                        "close_on_trigger": False,
                        "time_in_force": "PostOnly",
                        "api_key": self.api_key,
                        "timestamp": "1542782900000",
                        "recv_window": "93800000000",
                        "reduce_only": False,
                    }
                    print("买单参数====》", paramas)
                    log.logger.info("买单参数====》" + str(paramas))
                    signdic = self.CreateSign(paramas, self.screatkey)
                    try:
                        createbuy_Res = self.createorder(paramas, signdic)
                        buyorder_id = createbuy_Res['result']['order_id']
                        print("下买单成功==>", buyorder_id)
                        log.logger.info("下买单成功==>" + str(buyorder_id))
                        # update monitordic
                        inint_monitor_list[index]['buy_price_order_id'] = buyorder_id
                        inint_monitor_list[index]['buy_price_status'] = 1
                    except Exception as e:
                        print(e, "网络波动下单失败!")
                        log.logger.info(str(e) + "网络波动下单失败!")
            elif value['buy_price_status'] == 0 and value['sell_price_status'] == 1:
                # 买单未挂，卖单已挂，正常订单
                # print("买单未挂，卖单已挂，正常")
                pass
            elif value['buy_price_status'] == 1 and value['sell_price_status'] == 0:
                # print("买单已挂，卖单未挂，正常")
                pass
            elif value['buy_price_status'] == 1 and value['sell_price_status'] == 1:
                # print("卖单和买单都挂了，存在问题，需排查！")
                pass

    # 身份认证
    def BuildMysign(self):
        api_key = self.api_key
        secret_key = self.secret_key
        url = 'GET/realtime'
        expires = '1644531840000'
        # print expires
        sign = url + expires
        # print sign
        hash = hmac.new(bytes(secret_key, 'utf-8'), bytes(sign, 'utf-8'), hashlib.sha256)
        signature = hash.hexdigest()
        params = {
            "api_key": api_key,
            "expires": expires,
            "signature": signature
        }
        param = ''
        for key in params.keys():
            param += key + '=' + str(params[key]) + '&'
        param = param[:-1]
        return params

    def on_message_private(self,message):
        '''
        接收私有的信息
        :param ws:
        :param message:
        :return:
        '''
        global start_time
        # print(message)
        # 检查时间，发送心跳
        now_time = time.time()
        if now_time - start_time > 30.0:
            self.send_ping()
            start_time = now_time
        try:
            dictmessage = json.loads(message)
            # print(dictmessage)
            if dictmessage['topic'] == 'order':
                order_list = dictmessage['data']
                self.update_topic_orderlist(order_list)
            else:
                pass
        except Exception as e:
            print(message)

    # 回调接收消息
    def on_message_public_order(self,message):
        global datalist
        global first_buy_price
        global first_sell_price
        global start_time
        # print(message)
        # 检查时间，发送心跳
        now_time = time.time()
        if now_time - start_time > 30.0:
            self.send_ping()
            start_time = now_time
        dicmessage = {}
        # print(message)
        try:
            dicmessage = ast.literal_eval(message)
        except Exception as e:
            print("=======>", message)
        if len(dicmessage) > 0 and dicmessage['type'] == 'snapshot':
            datalist = dicmessage['data']['order_book']
            print("++++++++++", datalist)
        elif len(dicmessage) > 0 and dicmessage['type'] == 'delta' and len(datalist) > 0:
            first_buy_price, first_sell_price = self.fix_l2_orderbook(datalist, dicmessage)
            # rint("第一档买价:",first_buy_price,"第一档卖价:",first_sell_price)
        else:
            pass

        # time.sleep(2000)
        #

        # on_open(ws)

    # 处理数据
    def fix_l2_orderbook(self,oldmessage, message):
        '''
        修正最新的orderbook
        :param message:
        :return:
        '''
        deletelist = message['data']['delete']
        updatelist = message['data']['update']
        insertlist = message['data']['insert']
        # print(deletelist,updatelist,insertlist)
        # 处理删除的数据
        if len(deletelist) > 0:

            for d in deletelist:
                temid = d['id']
                for m in oldmessage:
                    if temid == m['id']:
                        oldmessage.remove(m)
        if len(updatelist) > 0:
            for u in updatelist:
                temid = u['id']
                for n in oldmessage:
                    if temid == n['id']:
                        index = oldmessage.index(n)
                        oldmessage[index] = u
        if len(insertlist) > 0:
            for i in insertlist:
                oldmessage.append(i)
        # return oldmessage
        # 返回最小的卖价和最大的买价
        # buylist = []
        buypricelist = []
        # selllist = []
        sellpricelist = []
        for l in oldmessage:
            if l['side'] == 'Buy':
                # buylist.append(l)
                buypricelist.append(float(l['price']))
            elif l['side'] == 'Sell':
                # selllist.append(l)
                sellpricelist.append(float(l['price']))
            else:
                pass
        # 排序价格
        buypricelist.sort()
        sellpricelist.sort()
        return float(buypricelist[-1]), float(sellpricelist[0])

    # 出现错误时执行
    def on_error(self, error):
        print(error)

    # 接公共行情的推送
    def on_open_public(self):
        self.ws.send('{"op": "subscribe", "args": ["orderBookL2_25.'+self.symbol+'"]}')

    # 开始连接时执行，需要订阅的消息和其它操作都要在这里完成
    # 接私有的推送
    def on_open_private(self):
        params = self.BuildMysign()
        # auth_str ='{"op":"auth","args":["cckaJkBPNVLdx6Qxtj","1644531840000","'+sigture+'"]}'
        # print(auth_str)
        # ws.send(json.dumps(auth_str))
        self.ws.send(json.dumps({
            "op": "auth",
            "args": [params["api_key"], params["expires"], params['signature']]
        }))
        # ws.send('{"op":"subscribe","args":["trade"]}')
        # ws.send('{"op":"subscribe","args":["instrument_info.100ms.BTCUSDT"]}')
        # ws.send('{"op":"subscribe","args":["kline.BTCUSD.1m"]}')
        # ws.send('{"op": "subscribe", "args": ["orderBookL2_25.BTCUSDT"]}')
        # ws.send('{"op":"subscribe","args":["liquidation.ETHUSDT"]}')
        # ws.send('{"op":"subscribe","args":["liquidation.ADAUSDT"]}')
        # ws.send('{"op":"subscribe","args":["liquidation.BNBUSDT"]}')
        # ws.send('{"op":"subscribe","args":["liquidation.LINKUSDT"]}')
        # ws.send('{"op":"subscribe","args":["liquidation.LTCUSDT"]}')
        # ws.send('{"op": "subscribe", "args": ["orderBook25.BTCUSD"]}')
        # ws.send('{"op": "subscribe", "args": ["orderBookL2_25.EOSUSD"]}')
        # ws.send('{"op": "subscribe", "args": ["instrument_info.100ms.EOSUSD"]}')
        # ws.send('{"op":"subscribe","args":["position"]}')
        self.ws.send('{"op":"subscribe","args":["order"]}')  # 活动单订阅
        self.ws.send('{"op": "subscribe", "args": ["wallet"]}')  # 钱包信息订阅
        self.ws.send('{"op": "subscribe", "args": ["position"]}')  # 个人持仓订阅
        # ws.send('{"op":"subscribe","args":["execution"]}')
        # ws.send('{"op":"subscribe","args":["stop_order"]}')
        # ws.send('{"op":"subscribe","args":["execution"]}')
        # ws.send('{"op":"subscribe","args":["recently_trade.100ms.BTCUSD"]}')
        # ws.send('{"op":"subscribe","args":["instrument_info.100ms.BTCUSDZ21"]}')
        # ws.send('{"op":"subscribe","args":["order"]}')
        # ws.send('{"op":"subscribe", "args":["stop_order"]}')
        # ws.send('{"op":"subscribe","args":["candle.1.BTCUSD"]}')
        # ws.send('{"op":"subscribe","args":["klineV2.1.BTCUSD"]}')
        # ws.send('{"op": "subscribe", "args": ["index_market_data_25.20ms.BTCUSD"]}')
        # ws.send('{"op": "subscribe", "args": ["index_quote_20.100ms.BTCUSD"]}')
        # ws.send('{"op":"subscribe","args":["klineV2.1.BTCUSD"]}')
        # ws.send('{"op": "subscribe", "args": ["orderBook_200.100ms.BTCUSD"]}');
        # ws.send('{"op": "subscribe", "args": ["orderBookL2_25.BTCUSDT"]}')

    # 关闭连接时执行
    def on_close(self):
        print("### closed ###")
        print(self.ws)

    # 发送心跳包
    def send_ping(self):
        self.ws.send('{"op":"ping"}')

    # 创建公共行情的推送

    # 创建websocket连接
    def ws_main(self,host):
        websocket.enableTrace(True)
        # host = "wss://stream-testnet.bybit.com/realtime_private?" + param
        # host = "ws://stream.trade-a-test-1.bybit.com/realtime"
        # host = "wss://stream.bybit.com/realtime_public"
        # host ="wss://stream.bybit.com/realtime_private"
        # # host = "ws://stream.trade-b-test-1.bybit.com/realtime"
        singed = host.split("/")[-1]
        if singed == "realtime_private":
            self.ws = websocket.WebSocketApp(host,
                                        on_message=self.on_message_private,
                                        on_error=self.on_error,
                                        on_close=self.on_close,
                                        on_open=self.on_open_private
                                        )

            self.ws.run_forever(ping_interval=30, http_proxy_host="127.0.0.1", http_proxy_port=1087,
                           sslopt={"cert_reqs": ssl.CERT_NONE})
        elif singed == "realtime_public":
            self.ws = websocket.WebSocketApp(host,
                                        on_message=self.on_message_public_order,
                                        on_error=self.on_error,
                                        on_close=self.on_close,
                                        on_open=self.on_open_public
                                        )
            # ws.run_forever(ping_interval=10, http_proxy_host="127.0.0.1", http_proxy_port=1087,
            #                sslopt={"cert_reqs": ssl.CERT_NONE})
            self.ws.run_forever(ping_interval=30, http_proxy_host="127.0.0.1", http_proxy_port=1087,
                           sslopt={"cert_reqs": ssl.CERT_NONE})
        # ws.run_forever(ping_interval=10)

    def mainthread(self):
        '''
        网格主线程
        :return:
        '''
        self.Init_Monitor_Order(self.symbol, self.money, self.gridnum, self.side, self.bttomprice, self.topprice, self.leverage, self.symbol_min_qty, self.UnPL)
        while 1:
            self.Monitor()
            time.sleep(5)



class Application(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("测试tt")
        self.geometry("1060x720")
        self.baseframe = tk.Frame()
        self.baseframe.grid(padx=0, pady=0)
        self.configsetting = tk.Frame(self.baseframe, width=1060, height=240)
        self.showorders = tk.Frame(self.baseframe, width=1060, height=440)
        self.showsumary = tk.Frame(self.baseframe, width=1060, height=40, bg='#FF0000')

        # 往配置页面上新增组建
        self.partlabel = tk.Label(self.configsetting, text='参数设置')
        self.symbollabel = tk.Label(self.configsetting, text='币种选择:')
        self.symbolCombobox = ttk.Combobox(self.configsetting, values=["BTCUSDT", "ETHUSDT"],width=8)
        self.invenstmoneylabel = tk.Label(self.configsetting, text='投入金额:')
        self.invenstmoneyEntry = tk.Entry(self.configsetting, width=7)
        self.apiKeylabel = tk.Label(self.configsetting, text='apiKey:')
        self.apiKeyEntry = tk.Entry(self.configsetting, width=7)
        self.SecreatKeylabel = tk.Label(self.configsetting, text='SecreatKey:')
        self.SecreatKeyEntry = tk.Entry(self.configsetting, width=5)
        self.grid_numlabel = tk.Label(self.configsetting, text='网格数量:')
        self.grid_numEntry = tk.Entry(self.configsetting, width=5)
        self.leveragelabel = tk.Label(self.configsetting, text='杠杆:')
        self.leverageEntry = tk.Entry(self.configsetting, width=6)
        self.bottom_pricelabel = tk.Label(self.configsetting, text='网格区间最低价:')
        self.bottom_priceEntry = tk.Entry(self.configsetting, width=9)
        self.top_pricelabel = tk.Label(self.configsetting, text='网格区间最高价:')
        self.top_priceEntry = tk.Entry(self.configsetting, width=12)
        self.Margin_Methodlabel = tk.Label(self.configsetting, text='仓位模式:')
        self.Margin_MethodcomboExample = ttk.Combobox(self.configsetting, values=["全仓", "逐仓"], width=5)
        self.trade_label = tk.Label(self.configsetting, text='交易方向:')
        self.tradecombox = ttk.Combobox(self.configsetting, values=["做多", "做空"], width=8)
        self.min_size_label = tk.Label(self.configsetting, text='每格最低交易量:')
        self.min_siz_Entry = tk.Entry(self.configsetting, width=8)
        self.grid_profit_label = tk.Label(self.configsetting, text='每格利润:')
        self.grid_profit_Combobox = ttk.Combobox(self.configsetting,values=["1%", "2%","3%","4%","5%"], width=8)
        self.button1 = tk.Button(self.configsetting, text='开   始', width=15,command=self.start,bg='#BA55D3')
        self.stop_btn = tk.Button(self.configsetting, text='停   止', width=15, command=self.stop,bg='#6495ED')
        self.reslut_title = tk.Label(self.configsetting, text='计算结果:', width=6)
        self.clear_button = tk.Button(self.configsetting, text='清   空', width=10, command=self.clearText)
        self.result_data_text = tk.Text(self.configsetting, width=31, height=18)  # 处理结果展示
        self.result_data_text.config(highlightbackground='#8B8989')

        self.partlabel.grid(row=0, column=4, columnspan=3, sticky='W')
        self.reslut_title.grid(row=0, column=10, sticky='W')
        self.clear_button.grid(row=0, column=12, columnspan=2, sticky='W')
        self.symbollabel.grid(row=1, column=0, sticky='w', padx=1, pady=1)
        self.symbolCombobox.grid(row=1, column=1, sticky='w', padx=1, pady=1)
        self.invenstmoneylabel.grid(row=1, column=2, sticky='w', padx=1, pady=1)
        self.invenstmoneyEntry.grid(row=1, column=3, sticky='w', pady=1)
        self.apiKeylabel.grid(row=1, column=4, sticky='w', padx=1, pady=1)
        self.apiKeyEntry.grid(row=1, column=5, sticky='w', padx=1, pady=1)
        self.SecreatKeylabel.grid(row=1, column=6, sticky='w', padx=1, pady=1)
        self.SecreatKeyEntry.grid(row=1, column=7, sticky='w', padx=1, pady=1)
        self.grid_numlabel.grid(row=1, column=8, sticky='w', padx=1, pady=1)
        self.grid_numEntry.grid(row=1, column=9, sticky='w', padx=1, pady=1)
        self.leveragelabel.grid(row=2, column=0, sticky='w', padx=1, pady=1)
        self.leverageEntry.grid(row=2, column=1, sticky='w', padx=1, pady=1)
        self.bottom_pricelabel.grid(row=2, column=2, sticky='w', padx=1, pady=1)
        self.bottom_priceEntry.grid(row=2, column=3, columnspan=2, sticky='w', padx=1, pady=1)
        self.top_pricelabel.grid(row=2, column=5, sticky='w', padx=1, pady=1)
        self.top_priceEntry.grid(row=2, column=6, columnspan=2, sticky='w', padx=1, pady=1)
        self.Margin_Methodlabel.grid(row=2, column=8, sticky='w', pady=1)
        self.Margin_MethodcomboExample.current(1)
        self.Margin_MethodcomboExample.grid(row=2, column=9, sticky='w', padx=1, pady=1)
        self.trade_label.grid(row=3, column=0, sticky='w', padx=1, pady=1)
        self.tradecombox.current(0)
        self.tradecombox.grid(row=3, column=1, sticky='w', padx=1, pady=1)
        self.min_size_label.grid(row=3, column=2, sticky='w', padx=1, pady=1)
        self.min_siz_Entry.grid(row=3, column=3, columnspan=2, sticky='w', padx=1, pady=1)
        self.grid_profit_label.grid(row=3,column=5,sticky='w', padx=1, pady=1)
        self.grid_profit_Combobox.current(0)
        self.grid_profit_Combobox.grid(row=3,column=6,columnspan=2,sticky='w', padx=1,pady=1)
        self.button1.grid(row=3, column=8, columnspan=2, sticky='w', padx=1, pady=1)
        self.stop_btn.grid(row=4, column=8, columnspan=2, sticky='w', padx=1, pady=1)
        self.result_data_text.grid(row=1, column=10, rowspan=12, columnspan=12, sticky='e', padx=1, pady=1)

        #在showerorders 上展示表格
        self.sheet = Sheet(self.showorders,
                           data=history_list,
                           show_top_left=False, headers=["币对", "结单时间", "结单金额","结单收益","币","%"],
                           width=750,
                           height=400,
                           empty_horizontal=0,
                           )
        self.sheet.enable_bindings()
        self.sheet.grid(row=0, column=0,padx=1, pady=1,sticky='nswe')
        self.configsetting.grid(row=0, column=0, padx=1, pady=1)
        self.showorders.grid(row=1, column=0, padx=1, pady=1,sticky='nswe')
        self.showsumary.grid(row=2, column=0, padx=1, pady=1)


    def start(self):
        '''
        开始获取信息获取参数
        '''
        global private_thread
        global public_thread
        # 禁止 按钮点击
        self.button1["state"] = "disabled"
        # 获取币对  只写了btcusdt的
        symbol = str(self.symbolCombobox.get())  #获取货币对
        invenstmoney = str(self.invenstmoneyEntry.get())  #获取投资额
        apiKey = str(self.apiKeyEntry.get())  #获取apikey
        SecreatKey = str(self.SecreatKeyEntry.get())  #获取scraetkey
        grid_num = str(self.grid_numEntry.get())  #获取网格数量
        leverage = str(self.leverageEntry.get())  #获取杠杆
        bottom_price= str(self.bottom_priceEntry.get())  #获取网格底价
        top_price = str(self.top_priceEntry.get())  #获取网格最高价
        Margin_Method = str(self.Margin_MethodcomboExample.get())  #获取仓位模式
        trade = str(self.tradecombox.get())  #获取交易方向
        min_size = str(self.min_siz_Entry.get())  #每格最低交易量
        grid_profit = str(self.grid_profit_Combobox.get())  #每格利润

        if Margin_Method =="全仓":
            Margin_Method = 'cross'
        elif Margin_Method =="逐仓":
            Margin_Method = 'assot'

        if trade =="做多":
            trade = "long"
        elif trade =="做空":
            trade = "short"

        grid_profit=float(grid_profit[0:1])*0.01

        print(symbol, invenstmoney, apiKey, SecreatKey, grid_num,
              leverage, bottom_price, top_price, Margin_Method, trade, min_size, grid_profit)

        print("开始挂单执行")

        private_host = "wss://stream.bybit.com/realtime_private"
        public_host = "wss://stream.bybit.com/realtime_public"
        # public_host = "wss://stream-testnet.bybit.com/realtime_public"
        # private_host = "wss://stream-testnet.bybit.com/realtime_private"
        tradingclass = Trading_srv(apiKey,SecreatKey,symbol,invenstmoney,grid_num,trade,bottom_price,top_price,leverage,min_size,grid_profit)
        private_thread = threading.Thread(target=tradingclass.ws_main, args=(private_host,))
        public_thread = threading.Thread(target=tradingclass.ws_main, args=(public_host,))
        grid_thread = threading.Thread(target=tradingclass.mainthread,args=())
        orders_monitor_thread = threading.Thread(target=self.monitorOrder,args=())

        private_thread.start()

        print("私有推送开启")
        time.sleep(2)
        public_thread.start()
        time.sleep(3)
        print("行情推送开启")
        grid_thread.start()
        print("grid线程启动")
        # 开启监控
        orders_monitor_thread.start()
        print("监控已开启")



    def monitorOrder(self):
        '''
        监控刷新已完成的订单
        :return:
        '''
        while 1:
            global history_list
            global history_list_len
            global private_thread
            global public_thread
            global grid_thread
            global notice_message
            if len(history_list)>history_list_len:
                print("here is the new!",history_list)
                #有新增
                self.sheet.set_sheet_data(data=history_list,
                               reset_col_positions=True,
                               reset_row_positions=True,
                               redraw=True,
                               verify=False,
                               reset_highlights=False)
                history_list_len = len(history_list)
            else:
                pass

            if private_thread.is_alive()==False or public_thread.is_alive()==False:
                notice_message=notice_message+"推送中断！\n"
                # 将必要日志写到表格
                self.result_data_text.insert(1,notice_message)
            # 10秒钟扫描一次
            time.sleep(10)

    def _async_raise(self,tid, exctype):
        """raises the exception, performs cleanup if needed"""
        tid = ctypes.c_long(tid)
        if not inspect.isclass(exctype):
            exctype = type(exctype)
        res = ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, ctypes.py_object(exctype))
        if res == 0:
            raise ValueError("invalid thread id")
        elif res != 1:
            # “““if it returns a number greater than one, you‘re in trouble,
            # and you should call it again with exc=NULL to revert the effect“““
            ctypes.pythonapi.PyThreadState_SetAsyncExc(tid, None)
            raise SystemError("PyThreadState_SetAsyncExc failed")

    def stop(self):
        global private_thread
        global public_thread
        global grid_thread
        self._async_raise(private_thread.ident, SystemExit)
        self._async_raise(public_thread.ident, SystemExit)
        self._async_raise(grid_thread.ident, SystemExit)
        self.button1["state"] = "normal"

    def clearText(self):
        self.result_data_text.insert(1,"")

if __name__ == '__main__':
    app =Application()
    app.mainloop()